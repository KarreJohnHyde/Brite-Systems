"""Train and evaluate the two trainable local ranking models.

The hosted answer generator is deliberately not fine-tuned: the repository has
no human-authored target answers, and Gemini is an external API.  This command
uses every canonical query exactly once as held-out data in two clause-disjoint
folds, then optionally fits a versioned candidate on all reviewed examples.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from config.settings import Settings
from evaluation.evaluate import run_evaluation
from src.artifact_integrity import sha256_directory
from src.lexical import BM25Index
from src.parser import get_embedding_text, parse_policy_manual
from src.pipeline import ingest_corpus
from training.data import (
    build_training_rows,
    clause_disjoint_folds,
    evidence_guard_ids,
    guarded_negative_ids,
    load_training_cases,
)
from training.metrics import binary_metrics, ranking_metrics

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = (
    ROOT / "evaluation" / "questions.json",
    ROOT / "evaluation" / "adversarial_questions.json",
)
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fine-tune the local bi-encoder and cross-encoder, run clause-disjoint "
            "cross-validation, build an immutable candidate index, and execute the RAG tests."
        )
    )
    parser.add_argument(
        "--run-name", required=True, help="New immutable candidate/run name"
    )
    parser.add_argument(
        "--corpus", type=Path, default=ROOT / "data" / "policy-manual.md"
    )
    parser.add_argument(
        "--question-files",
        type=Path,
        nargs="+",
        default=list(DEFAULT_QUESTIONS),
        help="Canonical query JSON files; defaults to core plus adversarial",
    )
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / "models" / "candidates"
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=ROOT / "evaluation" / "results" / "model-training",
    )
    parser.add_argument(
        "--index-root", type=Path, default=ROOT / "data" / "trained-indexes"
    )
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--negatives-per-query", type=int, default=3)
    parser.add_argument("--candidate-k", type=int, default=24)
    parser.add_argument("--embedding-epochs", type=float, default=2.0)
    parser.add_argument("--reranker-epochs", type=float, default=2.0)
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--embedding-learning-rate", type=float, default=2e-5)
    parser.add_argument("--reranker-learning-rate", type=float, default=1e-5)
    parser.add_argument("--skip-final-fit", action="store_true")
    parser.add_argument("--skip-end-to-end", action="store_true")
    args = parser.parse_args()
    if not args.run_name.strip() or any(char in args.run_name for char in "\\/:"):
        parser.error("--run-name must be a non-empty single path component")
    if args.negatives_per_query < 1:
        parser.error("--negatives-per-query must be positive")
    if args.candidate_k < 3:
        parser.error("--candidate-k must be at least 3")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds must not contain duplicates")
    return args


def main() -> int:
    args = _arguments()
    run_dir = (args.output_root / args.run_name).resolve()
    result_dir = (args.results_root / args.run_name).resolve()
    index_dir = (args.index_root / args.run_name).resolve()
    _reserve_new_outputs(
        run_dir, result_dir, index_dir, include_index=not args.skip_final_fit
    )
    _configure_local_training(run_dir)

    started = time.perf_counter()
    chunks = parse_policy_manual(args.corpus)
    known_clause_ids = {chunk.clause_id for chunk in chunks if chunk.clause_id}
    cases = load_training_cases(args.question_files, known_clause_ids=known_clause_ids)
    folds = clause_disjoint_folds(cases)
    by_id = {str(case["id"]): case for case in cases}

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "run_name": args.run_name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "split": "two-fold rotating clause-disjoint cross-validation",
            "held_out_once": True,
            "negative_mining": (
                "base dense plus BM25 RRF; excludes gold, same-section, adjacent, "
                "cross-referenced, and held-out evidence context"
            ),
            "generation_training": False,
            "generation_training_reason": (
                "No human-authored target answers are present and the configured Gemini model is hosted."
            ),
            "promotion_policy": (
                "Experimental candidate only; a new blind staff-query set is required before production promotion."
            ),
        },
        "environment": _environment_manifest(),
        "inputs": {
            "corpus": _file_manifest(Path(args.corpus)),
            "question_files": [
                _file_manifest(Path(path)) for path in args.question_files
            ],
            "queries": len(cases),
            "clauses": len(chunks),
            "expected_evidence_pairs": sum(
                len(case["expected_evidence_clause_ids"]) for case in cases
            ),
            "decision_counts": _counts(
                str(case["expected_decision"]) for case in cases
            ),
        },
        "base_models": {
            "bi_encoder": _model_reference(args.embedding_model, trainable=True),
            "cross_encoder": _model_reference(args.reranker_model, trainable=True),
            "gemini": {
                "reference": "configured hosted API model",
                "trainable_here": False,
                "test_scope": "behavioral provider and grounded-output contract only",
            },
            "deterministic_components": {
                "components": [
                    "stable hashing embeddings",
                    "BM25",
                    "FAISS IndexFlatIP",
                    "evidence/decision/conflict/citation/refusal rules",
                ],
                "trainable": False,
                "test_scope": "unit, retrieval, and end-to-end regression tests",
            },
        },
        "hyperparameters": {
            "seeds": args.seeds,
            "negatives_per_query": args.negatives_per_query,
            "candidate_k": args.candidate_k,
            "embedding_epochs": args.embedding_epochs,
            "reranker_epochs": args.reranker_epochs,
            "embedding_batch_size": args.embedding_batch_size,
            "reranker_batch_size": args.reranker_batch_size,
            "embedding_learning_rate": args.embedding_learning_rate,
            "reranker_learning_rate": args.reranker_learning_rate,
            "max_sequence_length": 256,
            "triplet_margin": 0.2,
            "optimizer": "adamw_torch",
            "device": "cpu",
        },
        "folds": {
            name: {
                "train_ids": [str(case["id"]) for case in split["train"]],
                "test_ids": [str(case["id"]) for case in split["test"]],
            }
            for name, split in folds.items()
        },
        "cross_validation": [],
    }
    _write_progress(report, result_dir)

    print("Loading cached base bi-encoder and creating leakage-safe rankings...")
    base_bi = _load_bi_encoder(args.embedding_model)
    base_dense = dense_rankings(base_bi, cases, chunks)
    base_hybrid = hybrid_rankings(cases, base_dense, chunks)
    del base_bi
    _release_memory()

    fold_rows: dict[str, dict[str, Any]] = {}
    heldout_pair_rows: dict[str, list[dict[str, Any]]] = {}
    for fold_name, split in folds.items():
        heldout_gold = {
            clause_id
            for case in split["test"]
            for clause_id in case["expected_evidence_clause_ids"]
        }
        heldout_guard = evidence_guard_ids(heldout_gold, chunks)
        train_negatives = _mine_negatives(
            split["train"],
            base_hybrid,
            chunks,
            limit=args.negatives_per_query,
            exclude_clause_ids=heldout_guard,
        )
        eval_negatives = _mine_negatives(
            split["test"],
            base_hybrid,
            chunks,
            limit=args.negatives_per_query,
        )
        fold_rows[fold_name] = build_training_rows(
            split["train"],
            chunks,
            train_negatives,
            negatives_per_query=args.negatives_per_query,
        )
        heldout_pair_rows[fold_name] = build_training_rows(
            split["test"],
            chunks,
            eval_negatives,
            negatives_per_query=args.negatives_per_query,
        )["pairs"]

    print("Loading cached base cross-encoder and measuring held-out baselines...")
    base_cross = _load_cross_encoder(args.reranker_model)
    base_reranked = reranked_rankings(
        base_cross,
        cases,
        base_dense,
        chunks,
        candidate_k=args.candidate_k,
    )
    baseline_binary_labels: list[float] = []
    baseline_binary_logits: list[float] = []
    for pair_rows in heldout_pair_rows.values():
        labels, logits = score_pairs(base_cross, pair_rows)
        baseline_binary_labels.extend(labels)
        baseline_binary_logits.extend(logits)
    del base_cross
    _release_memory()

    report["baseline"] = {
        "dense": ranking_metrics(cases, base_dense),
        "reranked": ranking_metrics(cases, base_reranked),
        "cross_encoder_binary": binary_metrics(
            baseline_binary_labels, baseline_binary_logits
        ),
    }
    _write_progress(report, result_dir)

    trained_metric_runs: list[dict[str, Any]] = []
    for seed in args.seeds:
        pooled_dense: dict[str, list[str]] = {}
        pooled_reranked: dict[str, list[str]] = {}
        pooled_labels: list[float] = []
        pooled_logits: list[float] = []
        seed_folds: list[dict[str, Any]] = []
        for fold_name, split in folds.items():
            print(f"Training {fold_name}, seed {seed}: bi-encoder...")
            fold_dir = run_dir / fold_name / f"seed_{seed}"
            bi_path = fold_dir / "bi_encoder"
            cross_path = fold_dir / "cross_encoder"
            rows = fold_rows[fold_name]
            fold_started = time.perf_counter()
            bi_model = train_bi_encoder(
                args.embedding_model,
                rows["triplets"],
                bi_path,
                seed=seed,
                epochs=args.embedding_epochs,
                batch_size=args.embedding_batch_size,
                learning_rate=args.embedding_learning_rate,
            )
            fold_dense = dense_rankings(bi_model, split["test"], chunks)

            # Re-mine training negatives with the just-trained first-stage model.
            trained_train_dense = dense_rankings(bi_model, split["train"], chunks)
            trained_train_hybrid = hybrid_rankings(
                split["train"], trained_train_dense, chunks
            )
            heldout_gold = {
                clause_id
                for case in split["test"]
                for clause_id in case["expected_evidence_clause_ids"]
            }
            trained_negatives = _mine_negatives(
                split["train"],
                trained_train_hybrid,
                chunks,
                limit=args.negatives_per_query,
                exclude_clause_ids=evidence_guard_ids(heldout_gold, chunks),
            )
            cross_rows = build_training_rows(
                split["train"],
                chunks,
                trained_negatives,
                negatives_per_query=args.negatives_per_query,
            )["pairs"]
            del bi_model
            _release_memory()

            print(f"Training {fold_name}, seed {seed}: cross-encoder...")
            cross_model = train_cross_encoder(
                args.reranker_model,
                cross_rows,
                cross_path,
                seed=seed,
                epochs=args.reranker_epochs,
                batch_size=args.reranker_batch_size,
                learning_rate=args.reranker_learning_rate,
            )
            fold_reranked = reranked_rankings(
                cross_model,
                split["test"],
                fold_dense,
                chunks,
                candidate_k=args.candidate_k,
            )
            labels, logits = score_pairs(cross_model, heldout_pair_rows[fold_name])
            del cross_model
            _release_memory()

            pooled_dense.update(fold_dense)
            pooled_reranked.update(fold_reranked)
            pooled_labels.extend(labels)
            pooled_logits.extend(logits)
            fold_result = {
                "fold": fold_name,
                "seed": seed,
                "train_queries": len(split["train"]),
                "test_queries": len(split["test"]),
                "bi_encoder_triplets": len(rows["triplets"]),
                "cross_encoder_pairs": len(cross_rows),
                "dense": ranking_metrics(split["test"], fold_dense),
                "reranked": ranking_metrics(split["test"], fold_reranked),
                "cross_encoder_binary": binary_metrics(labels, logits),
                "artifacts": {
                    "bi_encoder": _artifact_manifest(bi_path),
                    "cross_encoder": _artifact_manifest(cross_path),
                },
                "duration_seconds": round(time.perf_counter() - fold_started, 3),
            }
            seed_folds.append(fold_result)
            report["cross_validation"].append(fold_result)
            _write_progress(report, result_dir)

        if set(pooled_dense) != set(by_id) or set(pooled_reranked) != set(by_id):
            raise RuntimeError(
                "Cross-validation did not produce one held-out ranking per query"
            )
        seed_metrics = {
            "seed": seed,
            "dense": ranking_metrics(cases, pooled_dense),
            "reranked": ranking_metrics(cases, pooled_reranked),
            "cross_encoder_binary": binary_metrics(pooled_labels, pooled_logits),
            "folds": seed_folds,
        }
        trained_metric_runs.append(seed_metrics)

    report["cross_validation_summary"] = {
        "per_seed": trained_metric_runs,
        "dense": _summarize_runs([item["dense"] for item in trained_metric_runs]),
        "reranked": _summarize_runs([item["reranked"] for item in trained_metric_runs]),
        "cross_encoder_binary": _summarize_runs(
            [item["cross_encoder_binary"] for item in trained_metric_runs]
        ),
    }

    if not args.skip_final_fit:
        final_seed = args.seeds[0]
        print(
            f"Fitting final experimental candidate on all reviewed queries (seed {final_seed})..."
        )
        final_dir = run_dir / "final" / f"seed_{final_seed}"
        final_bi_path = final_dir / "bi_encoder"
        final_cross_path = final_dir / "cross_encoder"
        all_negatives = _mine_negatives(
            cases,
            base_hybrid,
            chunks,
            limit=args.negatives_per_query,
        )
        all_rows = build_training_rows(
            cases,
            chunks,
            all_negatives,
            negatives_per_query=args.negatives_per_query,
        )
        final_started = time.perf_counter()
        final_bi = train_bi_encoder(
            args.embedding_model,
            all_rows["triplets"],
            final_bi_path,
            seed=final_seed,
            epochs=args.embedding_epochs,
            batch_size=args.embedding_batch_size,
            learning_rate=args.embedding_learning_rate,
        )
        embedding_dimension = int(final_bi.get_embedding_dimension())
        final_dense = dense_rankings(final_bi, cases, chunks)
        final_train_hybrid = hybrid_rankings(cases, final_dense, chunks)
        final_negatives = _mine_negatives(
            cases,
            final_train_hybrid,
            chunks,
            limit=args.negatives_per_query,
        )
        final_cross_rows = build_training_rows(
            cases,
            chunks,
            final_negatives,
            negatives_per_query=args.negatives_per_query,
        )["pairs"]
        del final_bi
        _release_memory()
        final_cross = train_cross_encoder(
            args.reranker_model,
            final_cross_rows,
            final_cross_path,
            seed=final_seed,
            epochs=args.reranker_epochs,
            batch_size=args.reranker_batch_size,
            learning_rate=args.reranker_learning_rate,
        )
        final_reranked = reranked_rankings(
            final_cross,
            cases,
            final_dense,
            chunks,
            candidate_k=args.candidate_k,
        )
        final_labels, final_logits = score_pairs(final_cross, final_cross_rows)
        del final_cross
        _release_memory()

        candidate_settings = _candidate_settings(
            run_name=args.run_name,
            corpus=Path(args.corpus),
            index_dir=index_dir,
            embedding_model=final_bi_path,
            reranker_model=final_cross_path,
            embedding_dimension=embedding_dimension,
        )
        ingestion_report, index_manifest = ingest_corpus(candidate_settings)
        candidate: dict[str, Any] = {
            "seed": final_seed,
            "training_scope": "all reviewed queries; metrics below are in-sample regression only",
            "bi_encoder_triplets": len(all_rows["triplets"]),
            "cross_encoder_pairs": len(final_cross_rows),
            "dense_in_sample": ranking_metrics(cases, final_dense),
            "reranked_in_sample": ranking_metrics(cases, final_reranked),
            "cross_encoder_binary_in_sample": binary_metrics(
                final_labels, final_logits
            ),
            "artifacts": {
                "bi_encoder": _artifact_manifest(final_bi_path),
                "cross_encoder": _artifact_manifest(final_cross_path),
                "index": {
                    "path": _relative(index_dir),
                    "manifest": index_manifest,
                },
            },
            "corpus_report": ingestion_report.model_dump(mode="json"),
            "duration_seconds": round(time.perf_counter() - final_started, 3),
        }
        if not args.skip_end_to_end:
            print(
                "Running strict end-to-end core and adversarial evaluations with required reranking..."
            )
            candidate["end_to_end"] = {}
            for source in args.question_files:
                label = "adversarial" if "adversarial" in Path(source).stem else "core"
                evaluation = run_evaluation(
                    settings=candidate_settings,
                    quiet=True,
                    questions_path=source,
                    output_dir=result_dir / "end-to-end" / label,
                    respect_reranking=True,
                )
                candidate["end_to_end"][label] = {
                    "passes": evaluation["passes"],
                    "failures": evaluation["failures"],
                    "metrics": evaluation["metrics"],
                }
        report["final_candidate"] = candidate

    report["release_assessment"] = _release_assessment(report)
    report["status"] = "complete"
    report["duration_seconds"] = round(time.perf_counter() - started, 3)
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_progress(report, result_dir)
    print(f"Training and evaluation complete: {result_dir / 'report.md'}")
    return 0


def dense_rankings(
    model: Any, cases: list[dict[str, Any]], chunks: list[Any]
) -> dict[str, list[str]]:
    passages = [get_embedding_text(chunk) for chunk in chunks]
    passage_vectors = np.asarray(
        model.encode(
            passages,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype="float32",
    )
    query_vectors = np.asarray(
        model.encode(
            [str(case["question"]) for case in cases],
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype="float32",
    )
    scores = query_vectors @ passage_vectors.T
    clause_ids = [str(chunk.clause_id) for chunk in chunks]
    return {
        str(case["id"]): [
            clause_ids[index] for index in np.argsort(-scores[row], kind="stable")
        ]
        for row, case in enumerate(cases)
    }


def hybrid_rankings(
    cases: list[dict[str, Any]],
    dense: dict[str, list[str]],
    chunks: list[Any],
    *,
    rrf_k: int = 60,
) -> dict[str, list[str]]:
    lexical = BM25Index(chunks)
    output: dict[str, list[str]] = {}
    for case in cases:
        case_id = str(case["id"])
        lexical_ids = [
            str(chunk.clause_id)
            for chunk, _ in lexical.search(str(case["question"]), k=len(chunks))
        ]
        dense_ids = dense[case_id]
        dense_rank = {
            clause_id: rank for rank, clause_id in enumerate(dense_ids, start=1)
        }
        lexical_rank = {
            clause_id: rank for rank, clause_id in enumerate(lexical_ids, start=1)
        }
        output[case_id] = sorted(
            dense_ids,
            key=lambda clause_id: (
                -(
                    1.0 / (rrf_k + dense_rank[clause_id])
                    + (
                        1.0 / (rrf_k + lexical_rank[clause_id])
                        if clause_id in lexical_rank
                        else 0.0
                    )
                )
            ),
        )
    return output


def reranked_rankings(
    model: Any,
    cases: list[dict[str, Any]],
    first_stage: dict[str, list[str]],
    chunks: list[Any],
    *,
    candidate_k: int,
) -> dict[str, list[str]]:
    by_clause = {str(chunk.clause_id): chunk for chunk in chunks}
    output: dict[str, list[str]] = {}
    for case in cases:
        case_id = str(case["id"])
        ranking = first_stage[case_id]
        candidates = ranking[:candidate_k]
        pairs = [
            [str(case["question"]), _cross_encoder_text(by_clause[clause_id])]
            for clause_id in candidates
        ]
        scores = _predict_logits(model, pairs)
        ordered = [
            clause_id
            for _, clause_id in sorted(
                zip(scores, candidates, strict=True),
                key=lambda item: item[0],
                reverse=True,
            )
        ]
        output[case_id] = ordered + ranking[candidate_k:]
    return output


def score_pairs(
    model: Any, rows: list[dict[str, Any]]
) -> tuple[list[float], list[float]]:
    pairs = [[str(row["query"]), str(row["passage"])] for row in rows]
    labels = [float(row["label"]) for row in rows]
    return labels, _predict_logits(model, pairs)


def train_bi_encoder(
    base_model: str,
    rows: list[dict[str, Any]],
    destination: Path,
    *,
    seed: int,
    epochs: float,
    batch_size: int,
    learning_rate: float,
) -> Any:
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
    )
    from sentence_transformers.sentence_transformer.losses import (
        TripletDistanceMetric,
        TripletLoss,
    )

    _set_seed(seed)
    model = _load_bi_encoder(base_model)
    dataset = Dataset.from_list(
        [
            {
                "anchor": str(row["anchor"]),
                "positive": str(row["positive"]),
                "negative": str(row["negative"]),
            }
            for row in rows
        ]
    )
    loss = TripletLoss(
        model,
        distance_metric=TripletDistanceMetric.COSINE,
        triplet_margin=0.2,
    )
    args = SentenceTransformerTrainingArguments(
        output_dir=str(destination.parent / "bi-checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=learning_rate,
        warmup_steps=0.1,
        optim="adamw_torch",
        save_strategy="no",
        eval_strategy="no",
        logging_strategy="steps",
        logging_steps=max(1, len(dataset) // max(1, batch_size)),
        logging_first_step=True,
        report_to="none",
        use_cpu=True,
        full_determinism=True,
        seed=seed,
        data_seed=seed,
        dataloader_num_workers=0,
        dataloader_pin_memory=False,
        disable_tqdm=False,
    )
    trainer = SentenceTransformerTrainer(
        model=model, args=args, train_dataset=dataset, loss=loss
    )
    trainer.train()
    model.save_pretrained(str(destination), create_model_card=False)
    checkpoint_dir = destination.parent / "bi-checkpoints"
    if checkpoint_dir.exists() and not any(checkpoint_dir.iterdir()):
        checkpoint_dir.rmdir()
    return model


def train_cross_encoder(
    base_model: str,
    rows: list[dict[str, Any]],
    destination: Path,
    *,
    seed: int,
    epochs: float,
    batch_size: int,
    learning_rate: float,
) -> Any:
    import torch
    from datasets import Dataset
    from sentence_transformers import CrossEncoderTrainer, CrossEncoderTrainingArguments
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

    _set_seed(seed)
    model = _load_cross_encoder(base_model)
    dataset = Dataset.from_list(
        [
            {
                "query": str(row["query"]),
                "passage": str(row["passage"]),
                "label": float(row["label"]),
            }
            for row in rows
        ]
    )
    loss = BinaryCrossEntropyLoss(model, activation_fn=torch.nn.Identity())
    args = CrossEncoderTrainingArguments(
        output_dir=str(destination.parent / "cross-checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=learning_rate,
        warmup_steps=0.1,
        optim="adamw_torch",
        save_strategy="no",
        eval_strategy="no",
        logging_strategy="steps",
        logging_steps=max(1, len(dataset) // max(1, batch_size)),
        logging_first_step=True,
        report_to="none",
        use_cpu=True,
        full_determinism=True,
        seed=seed,
        data_seed=seed,
        dataloader_num_workers=0,
        dataloader_pin_memory=False,
        disable_tqdm=False,
    )
    trainer = CrossEncoderTrainer(
        model=model, args=args, train_dataset=dataset, loss=loss
    )
    trainer.train()
    model.save_pretrained(str(destination), create_model_card=False)
    checkpoint_dir = destination.parent / "cross-checkpoints"
    if checkpoint_dir.exists() and not any(checkpoint_dir.iterdir()):
        checkpoint_dir.rmdir()
    return model


def _load_bi_encoder(reference: str) -> Any:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        reference,
        device="cpu",
        local_files_only=True,
    )
    model.max_seq_length = 256
    return model


def _load_cross_encoder(reference: str) -> Any:
    import torch
    from sentence_transformers import CrossEncoder

    return CrossEncoder(
        reference,
        device="cpu",
        local_files_only=True,
        num_labels=1,
        max_length=256,
        activation_fn=torch.nn.Identity(),
    )


def _predict_logits(model: Any, pairs: list[list[str]]) -> list[float]:
    import torch

    scores = model.predict(
        pairs,
        batch_size=32,
        show_progress_bar=False,
        activation_fn=torch.nn.Identity(),
        apply_softmax=False,
        convert_to_numpy=True,
    )
    flattened = np.asarray(scores, dtype="float64").reshape(-1)
    if len(flattened) != len(pairs) or not np.isfinite(flattened).all():
        raise RuntimeError("Cross-encoder returned invalid logits")
    return [float(score) for score in flattened]


def _mine_negatives(
    cases: list[dict[str, Any]],
    rankings: dict[str, list[str]],
    chunks: list[Any],
    *,
    limit: int,
    exclude_clause_ids: set[str] | None = None,
) -> dict[str, list[str]]:
    return {
        str(case["id"]): guarded_negative_ids(
            case,
            rankings[str(case["id"])],
            chunks,
            limit=limit,
            exclude_clause_ids=exclude_clause_ids or (),
        )
        for case in cases
    }


def _candidate_settings(
    *,
    run_name: str,
    corpus: Path,
    index_dir: Path,
    embedding_model: Path,
    reranker_model: Path,
    embedding_dimension: int,
) -> Settings:
    candidate_data = index_dir / "processed"
    return Settings(
        project_root=ROOT,
        corpus_path=corpus.resolve(),
        processed_path=candidate_data / "chunks.json",
        corpus_report_path=candidate_data / "corpus-report.json",
        index_dir=index_dir,
        findings_path=ROOT / "data" / "policy_findings.json",
        contacts_path=ROOT / "data" / "contacts.json",
        embedding_backend="sentence-transformers",
        embedding_model=str(embedding_model.resolve()),
        embedding_dimension=embedding_dimension,
        reranker_model=str(reranker_model.resolve()),
        enable_hybrid_search=True,
        enable_reranking=True,
        require_reranker=True,
        enable_neighbor_retrieval=True,
        enable_contradiction_check=True,
        enable_claim_validation=True,
        initial_retrieval_k=24,
        rerank_k=24,
        final_k=6,
        rrf_k=60,
        refusal_threshold=0.58,
        direct_coverage_threshold=0.34,
        llm_provider="deterministic",
        log_level="WARNING",
    )


def _reserve_new_outputs(
    run_dir: Path,
    result_dir: Path,
    index_dir: Path,
    *,
    include_index: bool,
) -> None:
    targets = [run_dir, result_dir] + ([index_dir] if include_index else [])
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError(
            "Training outputs are immutable; choose a new --run-name. Existing: "
            + ", ".join(existing)
        )
    run_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)


def _configure_local_training(run_dir: Path) -> None:
    cache = run_dir / "runtime-cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_DATASETS_CACHE", str(cache / "datasets"))
    os.environ.setdefault("TMP", str(cache / "tmp"))
    os.environ.setdefault("TEMP", str(cache / "tmp"))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    (cache / "tmp").mkdir(parents=True, exist_ok=True)


def _set_seed(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _release_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _cross_encoder_text(chunk: Any) -> str:
    return f"{chunk.section_title or chunk.part_title or chunk.document_name}. {chunk.text}"


def _model_reference(reference: str, *, trainable: bool) -> dict[str, Any]:
    return {
        "reference": reference,
        "cached_revision": _cached_revision(reference),
        "trainable_here": trainable,
    }


def _cached_revision(reference: str) -> str | None:
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(reference, "config.json")
        if isinstance(cached, str):
            parts = Path(cached).parts
            if "snapshots" in parts:
                return parts[parts.index("snapshots") + 1]
    except (ImportError, IndexError, OSError, TypeError, ValueError):
        return None
    return None


def _artifact_manifest(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return {
        "path": _relative(path),
        "sha256": sha256_directory(path),
        "files": len(files),
        "bytes": sum(item.stat().st_size for item in files),
    }


def _file_manifest(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    data = resolved.read_bytes()
    return {
        "path": _relative(resolved),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _environment_manifest() -> dict[str, Any]:
    packages = {}
    for name in (
        "torch",
        "sentence-transformers",
        "transformers",
        "datasets",
        "accelerate",
        "faiss-cpu",
        "numpy",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    try:
        import torch

        torch_info = {
            "version": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
        }
    except ImportError:
        torch_info = {"version": None, "cuda_available": False}
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "torch": torch_info,
        "packages": packages,
    }


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _summarize_runs(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not metrics:
        return {}
    summary: dict[str, Any] = {}
    for key in metrics[0]:
        values = [item[key] for item in metrics]
        if all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ):
            summary[key] = {
                "mean": round(statistics.fmean(values), 6),
                "stddev": round(statistics.pstdev(values), 6),
            }
    return summary


def _release_assessment(report: dict[str, Any]) -> dict[str, Any]:
    """Make a conservative, metric-backed recommendation without auto-promoting."""

    baseline_ranking = report["baseline"]["reranked"]
    trained_ranking = report["cross_validation_summary"]["reranked"]
    baseline_binary = report["baseline"]["cross_encoder_binary"]
    trained_binary = report["cross_validation_summary"]["cross_encoder_binary"]
    deltas = {
        "reranked_recall_at_3": round(
            trained_ranking["recall_at_3"]["mean"] - baseline_ranking["recall_at_3"],
            6,
        ),
        "reranked_recall_at_6": round(
            trained_ranking["recall_at_6"]["mean"] - baseline_ranking["recall_at_6"],
            6,
        ),
        "reranked_recall_at_10": round(
            trained_ranking["recall_at_10"]["mean"] - baseline_ranking["recall_at_10"],
            6,
        ),
        "reranked_mrr": round(
            trained_ranking["mrr"]["mean"] - baseline_ranking["mrr"], 6
        ),
        "reranked_ndcg_at_10": round(
            trained_ranking["ndcg_at_10"]["mean"] - baseline_ranking["ndcg_at_10"],
            6,
        ),
        "cross_encoder_roc_auc": round(
            trained_binary["roc_auc"]["mean"] - baseline_binary["roc_auc"], 6
        ),
    }
    end_to_end = report.get("final_candidate", {}).get("end_to_end", {})
    safety_regression = bool(end_to_end) and any(
        result.get("failures", 1) for result in end_to_end.values()
    )
    recall_improved = deltas["reranked_recall_at_6"] > 0
    auc_not_worse = deltas["cross_encoder_roc_auc"] >= 0
    reasons = []
    if not recall_improved:
        reasons.append(
            "Held-out reranked Recall@6 did not improve over the pretrained baseline."
        )
    if not auc_not_worse:
        reasons.append("Held-out cross-encoder pairwise ROC AUC decreased.")
    if not end_to_end:
        reasons.append("Strict end-to-end candidate evaluation was not run.")
    elif safety_regression:
        reasons.append("At least one strict end-to-end case regressed.")
    else:
        reasons.append(
            "All recorded strict end-to-end core and adversarial cases passed."
        )
    reasons.append(
        "Only 33 reviewed queries and one reproducible seed were available; no blind staff-query set exists."
    )
    eligible = (
        recall_improved and auc_not_worse and bool(end_to_end) and not safety_regression
    )
    return {
        "decision": (
            "ELIGIBLE_FOR_BLIND_VALIDATION" if eligible else "KEEP_PRETRAINED_BASELINE"
        ),
        "candidate_remains_opt_in": True,
        "held_out_deltas": deltas,
        "reasons": reasons,
    }


def _write_progress(report: dict[str, Any], result_dir: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (result_dir / "report.md").write_text(_markdown(report), encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Local model training and evaluation",
        "",
        f"**Status:** {report['status']}",
        f"**Run:** `{report['run_name']}`",
        "",
        (
            "The bi-encoder and cross-encoder are the only trainable local models. "
            "Gemini is hosted and the deterministic retrieval/safety components have no learned weights."
        ),
        "",
        "## Dataset and split",
        "",
        f"- Queries: {report['inputs']['queries']}",
        f"- Clauses: {report['inputs']['clauses']}",
        f"- Expected evidence pairs: {report['inputs']['expected_evidence_pairs']}",
        "- Evaluation: every query held out once in two clause-disjoint folds",
        "",
    ]
    baseline = report.get("baseline")
    if baseline:
        lines.extend(_ranking_table("Pretrained baseline", baseline))
    summary = report.get("cross_validation_summary")
    if summary:
        lines.extend(
            [
                "## Trained held-out cross-validation",
                "",
                _summary_row("Dense", summary["dense"]),
                _summary_row("Reranked", summary["reranked"]),
                "",
            ]
        )
    candidate = report.get("final_candidate")
    if candidate:
        lines.extend(
            [
                "## Final experimental candidate",
                "",
                "This model was fitted on all reviewed queries. Its values are regression checks, not blind metrics.",
                "",
                f"- Dense in-sample Recall@6: {candidate['dense_in_sample']['recall_at_6']:.3f}",
                f"- Reranked in-sample Recall@6: {candidate['reranked_in_sample']['recall_at_6']:.3f}",
            ]
        )
        for label, result in candidate.get("end_to_end", {}).items():
            lines.append(
                f"- {label.title()} end-to-end: {result['passes']} passed, {result['failures']} failed"
            )
        lines.append("")
    assessment = report.get("release_assessment")
    if assessment:
        lines.extend(
            [
                "## Release assessment",
                "",
                f"**Decision:** `{assessment['decision']}`",
                "",
                *[f"- {reason}" for reason in assessment["reasons"]],
                "",
            ]
        )
    lines.extend(
        [
            "## Release decision",
            "",
            (
                "Keep this candidate opt-in until it improves held-out ranking without any safety regression "
                "and is validated on a newly collected blind staff-query set."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _ranking_table(title: str, metrics: dict[str, Any]) -> list[str]:
    dense = metrics["dense"]
    reranked = metrics["reranked"]
    return [
        f"## {title}",
        "",
        "| Stage | Recall@1 | Recall@6 | MRR | nDCG@10 |",
        "|---|---:|---:|---:|---:|",
        (
            f"| Dense | {dense['recall_at_1']:.3f} | {dense['recall_at_6']:.3f} | "
            f"{dense['mrr']:.3f} | {dense['ndcg_at_10']:.3f} |"
        ),
        (
            f"| Reranked | {reranked['recall_at_1']:.3f} | {reranked['recall_at_6']:.3f} | "
            f"{reranked['mrr']:.3f} | {reranked['ndcg_at_10']:.3f} |"
        ),
        "",
    ]


def _summary_row(label: str, summary: dict[str, Any]) -> str:
    return (
        f"- {label}: Recall@6 {summary['recall_at_6']['mean']:.3f} "
        f"(σ {summary['recall_at_6']['stddev']:.3f}), MRR {summary['mrr']['mean']:.3f} "
        f"(σ {summary['mrr']['stddev']:.3f})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
