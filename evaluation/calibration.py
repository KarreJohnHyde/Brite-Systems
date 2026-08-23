"""Offline, auditable threshold calibration over the source-derived cases."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    aggregate_results,
    compact_case_result,
    load_questions,
    score_case,
    validate_question_clause_ids,
)
from src.pipeline import GroundedAnswerPipeline  # noqa: E402


DEFAULT_REFUSAL_THRESHOLDS = (0.42, 0.48, 0.54, 0.58, 0.62, 0.68, 0.74)
DEFAULT_COVERAGE_THRESHOLDS = (0.24, 0.28, 0.34, 0.40)
QUESTIONS_PATH = ROOT / "evaluation" / "questions.json"
RESULTS_DIR = ROOT / "evaluation" / "results"
RESULTS_JSON = RESULTS_DIR / "calibration.json"
RESULTS_MARKDOWN = RESULTS_DIR / "calibration.md"
SELECTION_RULE = (
    "Lexicographic safety-first selection: minimize false ANSWERs, minimize missed "
    "CONFLICTs, maximize strict passes, maximize decision accuracy, maximize unsupported-"
    "claim safety, minimize false CONFLICTs, then prefer the candidate closest to the "
    "configured baseline."
)
OBJECTIVE_FORMULA = (
    "strict_pass_rate + 0.25*decision_accuracy + 0.50*unsupported_safety_rate + "
    "0.25*conflict_recall - 2.0*false_answer_rate"
)


def run_calibration(
    *,
    settings: Settings | None = None,
    refusal_thresholds: Iterable[float] | None = None,
    coverage_thresholds: Iterable[float] | None = None,
    questions_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Sweep support thresholds without an LLM, reranker, or network model."""

    configured = settings or Settings.from_env()
    if configured.embedding_backend != "hashing":
        raise ValueError(
            "Calibration is offline-only and requires EMBEDDING_BACKEND=hashing. "
            "Re-run `python main.py ingest --embedding-backend hashing` first."
        )
    offline = configured.model_copy(
        update={
            "embedding_backend": "hashing",
            "llm_provider": "deterministic",
            "enable_reranking": False,
        }
    )
    source = Path(questions_path) if questions_path else QUESTIONS_PATH
    target_dir = Path(output_dir) if output_dir else RESULTS_DIR
    questions = load_questions(source)

    refusal_values = _grid_values(
        refusal_thresholds or DEFAULT_REFUSAL_THRESHOLDS,
        offline.refusal_threshold,
    )
    coverage_values = _grid_values(
        coverage_thresholds or DEFAULT_COVERAGE_THRESHOLDS,
        offline.direct_coverage_threshold,
    )

    started = time.perf_counter()
    base_pipeline = GroundedAnswerPipeline.load(offline)
    known_clause_ids = {
        chunk.clause_id for chunk in base_pipeline.store.chunks if chunk.clause_id is not None
    }
    validate_question_clause_ids(questions, known_clause_ids)

    candidates: list[dict[str, Any]] = []
    for refusal_threshold in refusal_values:
        for coverage_threshold in coverage_values:
            candidate_settings = offline.model_copy(
                update={
                    "refusal_threshold": refusal_threshold,
                    "direct_coverage_threshold": coverage_threshold,
                }
            )
            pipeline = GroundedAnswerPipeline(
                candidate_settings,
                base_pipeline.embedding_engine,
                base_pipeline.store,
                llm_provider=None,
            )
            scored_cases: list[dict[str, Any]] = []
            for case in questions:
                case_started = time.perf_counter()
                answer = None
                error: BaseException | None = None
                try:
                    answer = pipeline.ask(case["question"], include_trace=True)
                except Exception as exc:
                    error = exc
                scored = score_case(
                    case,
                    answer,
                    elapsed_ms=(time.perf_counter() - case_started) * 1000.0,
                    error=error,
                )
                scored_cases.append(scored)
            metrics = aggregate_results(scored_cases)
            false_conflicts = sum(
                result["actual_decision"] == "CONFLICT"
                and result["expected_decision"] != "CONFLICT"
                for result in scored_cases
            )
            missed_conflicts = sum(
                result["expected_decision"] == "CONFLICT"
                and result["actual_decision"] != "CONFLICT"
                for result in scored_cases
            )
            objective = _objective(metrics)
            candidates.append(
                {
                    "candidate_id": f"r{refusal_threshold:.2f}_c{coverage_threshold:.2f}",
                    "refusal_threshold": refusal_threshold,
                    "direct_coverage_threshold": coverage_threshold,
                    "objective_score": round(objective, 6),
                    "false_answers": metrics["unsupported"]["false_answers"],
                    "missed_conflicts": missed_conflicts,
                    "false_conflicts": false_conflicts,
                    "metrics": metrics,
                    "cases": [compact_case_result(result) for result in scored_cases],
                }
            )

    baseline = _find_candidate(
        candidates,
        offline.refusal_threshold,
        offline.direct_coverage_threshold,
    )
    recommended = max(
        candidates,
        key=lambda candidate: _selection_key(
            candidate,
            baseline_refusal=offline.refusal_threshold,
            baseline_coverage=offline.direct_coverage_threshold,
        ),
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_type": "offline_threshold_calibration",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "questions_path": str(source.resolve()),
        "corpus_sha256": base_pipeline.store.manifest.get("corpus_sha256"),
        "offline_guarantees": {
            "embedding_backend": "hashing",
            "llm_provider": "deterministic",
            "reranking": False,
            "network_required": False,
        },
        "development_set_warning": (
            "Thresholds were selected on the same source-derived development set reported here; "
            "confirm them on a separate held-out set before treating the rates as generalization estimates."
        ),
        "selection_rule": SELECTION_RULE,
        "objective_formula": OBJECTIVE_FORMULA,
        "grid": {
            "refusal_thresholds": refusal_values,
            "direct_coverage_thresholds": coverage_values,
            "candidate_count": len(candidates),
        },
        "configured_baseline": _candidate_summary(baseline),
        "recommended": _candidate_summary(recommended),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "candidates": candidates,
    }

    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / RESULTS_JSON.name
    markdown_path = target_dir / RESULTS_MARKDOWN.name
    _write_text(json_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _write_text(markdown_path, _markdown_report(report))
    _print_summary(report, json_path, markdown_path)
    return report


def _objective(metrics: dict[str, Any]) -> float:
    return (
        metrics["strict_pass_rate"]
        + 0.25 * metrics["decision"]["accuracy"]
        + 0.50 * metrics["unsupported"]["safety_rate"]
        + 0.25 * metrics["conflict"]["decision_recall"]
        - 2.0 * metrics["unsupported"]["false_answer_rate"]
    )


def _selection_key(
    candidate: dict[str, Any],
    *,
    baseline_refusal: float,
    baseline_coverage: float,
) -> tuple[Any, ...]:
    metrics = candidate["metrics"]
    distance = abs(candidate["refusal_threshold"] - baseline_refusal) + abs(
        candidate["direct_coverage_threshold"] - baseline_coverage
    )
    return (
        -candidate["false_answers"],
        -candidate["missed_conflicts"],
        metrics["passes"],
        metrics["decision"]["accuracy"],
        metrics["unsupported"]["safety_rate"],
        -candidate["false_conflicts"],
        candidate["objective_score"],
        -distance,
    )


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "refusal_threshold": candidate["refusal_threshold"],
        "direct_coverage_threshold": candidate["direct_coverage_threshold"],
        "objective_score": candidate["objective_score"],
        "false_answers": candidate["false_answers"],
        "missed_conflicts": candidate["missed_conflicts"],
        "false_conflicts": candidate["false_conflicts"],
        "metrics": candidate["metrics"],
    }


def _find_candidate(
    candidates: list[dict[str, Any]],
    refusal_threshold: float,
    coverage_threshold: float,
) -> dict[str, Any]:
    return next(
        candidate
        for candidate in candidates
        if candidate["refusal_threshold"] == refusal_threshold
        and candidate["direct_coverage_threshold"] == coverage_threshold
    )


def _grid_values(values: Iterable[float], baseline: float) -> list[float]:
    normalized = {round(float(value), 4) for value in values}
    normalized.add(round(float(baseline), 4))
    if any(value < 0.0 or value > 1.0 for value in normalized):
        raise ValueError("Calibration thresholds must be in the inclusive range 0..1")
    return sorted(normalized)


def _markdown_report(report: dict[str, Any]) -> str:
    baseline = report["configured_baseline"]
    recommended = report["recommended"]
    lines = [
        "# Threshold Calibration — The Grounded Answer",
        "",
        f"**Generated (UTC):** {report['generated_at_utc']}",
        "**Mode:** deterministic hashing embeddings; no LLM, reranker, or network model",
        f"**Candidates evaluated:** {report['grid']['candidate_count']}",
        "",
        "## Recommendation",
        "",
        f"- Refusal threshold: **{recommended['refusal_threshold']:.2f}**",
        f"- Direct-coverage threshold: **{recommended['direct_coverage_threshold']:.2f}**",
        f"- Strict pass rate: **{recommended['metrics']['strict_pass_rate']:.1%}**",
        f"- Decision accuracy: **{recommended['metrics']['decision']['accuracy']:.1%}**",
        f"- False answers: **{recommended['false_answers']}**",
        f"- Missed conflicts: **{recommended['missed_conflicts']}**",
        "",
        f"> {report['development_set_warning']}",
        "",
        "## Selection policy",
        "",
        report["selection_rule"],
        "",
        f"Audit objective: `{report['objective_formula']}`",
        "",
        "## Configured baseline",
        "",
        f"Baseline `{baseline['candidate_id']}` passed {baseline['metrics']['passes']} / {baseline['metrics']['total']} strict cases with {baseline['metrics']['decision']['accuracy']:.1%} decision accuracy.",
        "",
        "## Sweep results",
        "",
        "| Candidate | Refusal | Coverage | Strict | Decision | ANSWER | REFUSE | CONFLICT | Retrieval | Citations | Safety | False answers | Missed conflicts |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    ordered = sorted(
        report["candidates"],
        key=lambda item: (
            item["refusal_threshold"],
            item["direct_coverage_threshold"],
        ),
    )
    for candidate in ordered:
        metrics = candidate["metrics"]
        label = candidate["candidate_id"]
        if label == recommended["candidate_id"]:
            label += " (recommended)"
        elif label == baseline["candidate_id"]:
            label += " (baseline)"
        lines.append(
            "| {label} | {refusal:.2f} | {coverage:.2f} | {strict:.1%} | {decision:.1%} | "
            "{answer:.1%} | {refuse:.1%} | {conflict:.1%} | {retrieval:.1%} | "
            "{citation:.1%} | {safety:.1%} | {false_answers} | {missed_conflicts} |".format(
                label=label,
                refusal=candidate["refusal_threshold"],
                coverage=candidate["direct_coverage_threshold"],
                strict=metrics["strict_pass_rate"],
                decision=metrics["decision"]["accuracy"],
                answer=metrics["answer"]["decision_recall"],
                refuse=metrics["refuse"]["decision_recall"],
                conflict=metrics["conflict"]["decision_recall"],
                retrieval=metrics["retrieval"]["micro_clause_recall"],
                citation=metrics["citation"]["micro_clause_recall"],
                safety=metrics["unsupported"]["safety_rate"],
                false_answers=candidate["false_answers"],
                missed_conflicts=candidate["missed_conflicts"],
            )
        )

    lines.extend(["", "## Recommended-candidate failures", ""])
    # Candidate summaries intentionally omit cases; recover them from full grid.
    full_recommended = next(
        candidate for candidate in report["candidates"] if candidate["candidate_id"] == recommended["candidate_id"]
    )
    failures = [case for case in full_recommended["cases"] if not case["overall_pass"]]
    if failures:
        for case in failures:
            lines.append(
                f"- **{case['id']}**: expected `{case['expected_decision']}`, got "
                f"`{case['actual_decision']}` — {', '.join(case['failure_types']) or 'strict check failed'}"
            )
    else:
        lines.append("No strict failures for the recommended candidate.")
    lines.append("")
    return "\n".join(lines)


def _print_summary(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    baseline = report["configured_baseline"]
    recommended = report["recommended"]
    print("OFFLINE THRESHOLD CALIBRATION")
    print(f"Candidates:          {report['grid']['candidate_count']}")
    print(
        f"Baseline:            r={baseline['refusal_threshold']:.2f}, "
        f"c={baseline['direct_coverage_threshold']:.2f}, "
        f"strict={baseline['metrics']['strict_pass_rate']:.1%}"
    )
    print(
        f"Recommended:         r={recommended['refusal_threshold']:.2f}, "
        f"c={recommended['direct_coverage_threshold']:.2f}, "
        f"strict={recommended['metrics']['strict_pass_rate']:.1%}"
    )
    print(f"False answers:       {recommended['false_answers']}")
    print(f"Missed conflicts:    {recommended['missed_conflicts']}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    run_calibration()
