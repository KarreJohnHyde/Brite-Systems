"""Strict end-to-end evaluation for The Grounded Answer.

Each question is sent through ``GroundedAnswerPipeline.ask`` using deterministic
answer construction. A case passes only when the final decision, retrieval,
citations, required facts, forbidden-claim checks, grounding checks, and output
contract all pass. Both JSON and Markdown artifacts retain complete answers and
auditable traces.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    aggregate_results,
    load_questions,
    score_case,
    validate_question_clause_ids,
)
from src.pipeline import GroundedAnswerPipeline  # noqa: E402


DEFAULT_QUESTIONS_PATH = ROOT / "evaluation" / "questions.json"
DEFAULT_RESULTS_DIR = ROOT / "evaluation" / "results"
DEFAULT_RESULTS_JSON = DEFAULT_RESULTS_DIR / "evaluation.json"
DEFAULT_RESULTS_MARKDOWN = DEFAULT_RESULTS_DIR / "evaluation.md"


def run_evaluation(
    *,
    settings: Settings | None = None,
    quiet: bool = False,
    questions_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the current question set through complete, deterministic responses."""

    configured = settings or Settings.from_env()
    deterministic = configured.model_copy(
        update={
            "llm_provider": "deterministic",
            "enable_reranking": False,
        }
    )
    source = Path(questions_path) if questions_path else DEFAULT_QUESTIONS_PATH
    target_dir = Path(output_dir) if output_dir else DEFAULT_RESULTS_DIR
    questions = load_questions(source)

    started = time.perf_counter()
    pipeline = GroundedAnswerPipeline.load(deterministic)
    known_clause_ids = {
        chunk.clause_id for chunk in pipeline.store.chunks if chunk.clause_id is not None
    }
    validate_question_clause_ids(questions, known_clause_ids)

    case_results: list[dict[str, Any]] = []
    for case in questions:
        case_started = time.perf_counter()
        answer = None
        error: BaseException | None = None
        try:
            answer = pipeline.ask(case["question"], include_trace=True)
        except Exception as exc:  # Preserve the rest of the evaluation run.
            error = exc
        elapsed_ms = (time.perf_counter() - case_started) * 1000.0
        scored = score_case(case, answer, elapsed_ms=elapsed_ms, error=error)
        scored["response"] = answer.model_dump(mode="json") if answer is not None else None
        case_results.append(scored)
        if not quiet or not scored["overall_pass"]:
            _print_case(scored)

    metrics = aggregate_results(case_results)
    generated_at = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "schema_version": 2,
        "run_type": "strict_end_to_end",
        "generated_at_utc": generated_at,
        "questions_path": str(source.resolve()),
        "corpus_path": str(deterministic.corpus_path),
        "corpus_sha256": pipeline.store.manifest.get("corpus_sha256"),
        "configuration": {
            "embedding_backend": deterministic.embedding_backend,
            "embedding_model": pipeline.embedding_engine.model_name,
            "hybrid_search": deterministic.enable_hybrid_search,
            "reranking": False,
            "neighbor_retrieval": deterministic.enable_neighbor_retrieval,
            "llm_provider": "deterministic",
            "initial_retrieval_k": deterministic.initial_retrieval_k,
            "final_k": deterministic.final_k,
            "refusal_threshold": deterministic.refusal_threshold,
            "direct_coverage_threshold": deterministic.direct_coverage_threshold,
        },
        "duration_seconds": round(time.perf_counter() - started, 3),
        "passes": metrics["passes"],
        "failures": metrics["failures"],
        "metrics": metrics,
        "cases": case_results,
    }
    report["requirements"] = _requirement_statuses(report)

    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / DEFAULT_RESULTS_JSON.name
    markdown_path = target_dir / DEFAULT_RESULTS_MARKDOWN.name
    _write_json(json_path, report)
    _write_text(markdown_path, _markdown_report(report))
    _print_summary(report, json_path, markdown_path)
    return report


def _print_case(result: dict[str, Any]) -> None:
    status = "PASS" if result["overall_pass"] else "FAIL"
    failures = ", ".join(result["failure_types"]) or "none"
    print(
        f"[{result['id']}] {status} | expected={result['expected_decision']} "
        f"actual={result['actual_decision']} | failures={failures}"
    )


def _print_summary(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    metrics = report["metrics"]
    print()
    print("STRICT END-TO-END EVALUATION")
    print(f"Cases:              {metrics['total']}")
    print(f"Passed / failed:    {metrics['passes']} / {metrics['failures']}")
    print(f"Strict pass rate:   {metrics['strict_pass_rate']:.1%}")
    print(f"Decision accuracy: {metrics['decision']['accuracy']:.1%}")
    print(f"Retrieval recall:  {metrics['retrieval']['micro_clause_recall']:.1%}")
    print(f"Citation recall:   {metrics['citation']['micro_clause_recall']:.1%}")
    print(f"Unsupported safety:{metrics['unsupported']['safety_rate']:>6.1%}")
    print()
    _print_requirement_block("CORE REQUIREMENTS", report["requirements"]["core"])
    print()
    _print_requirement_block("BONUS", report["requirements"]["bonus"])
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")


def _print_requirement_block(title: str, items: list[dict[str, Any]]) -> None:
    print(title)
    for item in items:
        status = "PASS" if item["pass"] else "FAIL"
        print(f"[{status}] {item['name']}")


def _requirement_statuses(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    metrics = report["metrics"]
    cases = report["cases"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    main_py = (ROOT / "main.py").read_text(encoding="utf-8") if (ROOT / "main.py").exists() else ""
    calibration_report = ROOT / "evaluation" / "results" / "calibration.md"

    def case_passes(decision: str) -> bool:
        return any(
            case["expected_decision"] == decision
            and case["actual_decision"] == decision
            and case["overall_pass"]
            for case in cases
        )

    core = [
        {
            "name": "Clause-level citation",
            "pass": metrics["citation"]["micro_clause_recall"] == 1.0
            and metrics["citation"]["integrity_rate"] == 1.0,
        },
        {
            "name": "Visible refusal",
            "pass": case_passes("REFUSE"),
        },
        {
            "name": "At least one correct refusal",
            "pass": case_passes("REFUSE"),
        },
        {
            "name": "10+ self-created test questions",
            "pass": metrics["total"] >= 10,
        },
        {
            "name": "Pass/fail results",
            "pass": all("overall_pass" in case and "failure_types" in case for case in cases),
        },
        {
            "name": "README clean-clone instructions",
            "pass": "Clean-clone setup" in readme and "python main.py ingest" in readme,
        },
    ]
    bonus = [
        {
            "name": "Contradiction surfaced",
            "pass": case_passes("CONFLICT"),
        },
        {
            "name": "Refusal threshold calibrated",
            "pass": calibration_report.exists() and "Recommended" in calibration_report.read_text(encoding="utf-8"),
        },
        {
            "name": "Citation source lookup",
            "pass": 'add_parser("source"' in main_py and 'aliases=["show-clause"]' in main_py,
        },
    ]
    return {"core": core, "bonus": bonus}


def _markdown_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Evaluation Results — The Grounded Answer",
        "",
        f"**Generated (UTC):** {report['generated_at_utc']}",
        f"**Run type:** `{report['run_type']}`",
        f"**Corpus SHA-256:** `{report.get('corpus_sha256') or 'unavailable'}`",
        f"**Embedding backend:** `{report['configuration']['embedding_backend']}`",
        "**LLM/provider:** deterministic; no generation API used",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Result |",
        "| :-- | --: |",
        f"| Strict cases passed | {metrics['passes']} / {metrics['total']} ({_percent(metrics['strict_pass_rate'])}) |",
        f"| Decision accuracy | {metrics['decision']['correct']} / {metrics['decision']['total']} ({_percent(metrics['decision']['accuracy'])}) |",
        f"| ANSWER decision precision / recall | {_state_result(metrics['answer'])} |",
        f"| REFUSE decision precision / recall | {_state_result(metrics['refuse'])} |",
        f"| CONFLICT decision precision / recall | {_state_result(metrics['conflict'])} |",
        f"| Expected evidence retrieval | {metrics['retrieval']['clauses_found']} / {metrics['retrieval']['clauses_expected']} ({_percent(metrics['retrieval']['micro_clause_recall'])}) |",
        f"| Required citation recall | {metrics['citation']['clauses_cited']} / {metrics['citation']['clauses_expected']} ({_percent(metrics['citation']['micro_clause_recall'])}) |",
        f"| Citation integrity | {metrics['citation']['integrity_passes']} / {metrics['total']} ({_percent(metrics['citation']['integrity_rate'])}) |",
        f"| Expected fact recall | {metrics['facts']['facts_found']} / {metrics['facts']['facts_expected']} ({_percent(metrics['facts']['micro_fact_recall'])}) |",
        f"| Unsupported-claim safety | {metrics['unsupported']['safe_cases']} / {metrics['total']} ({_percent(metrics['unsupported']['safety_rate'])}) |",
        f"| False answers on REFUSE/CONFLICT cases | {metrics['unsupported']['false_answers']} / {metrics['unsupported']['non_answer_cases']} ({_percent(metrics['unsupported']['false_answer_rate'])}) |",
        "",
        "## Requirement summary",
        "",
        "### Core requirements",
        "",
    ]
    lines.extend(_markdown_requirement_lines(report["requirements"]["core"]))
    lines.extend(
        [
            "",
            "### Bonus",
            "",
        ]
    )
    lines.extend(_markdown_requirement_lines(report["requirements"]["bonus"]))
    lines.extend(
        [
            "",
        "## Failure taxonomy",
        "",
        ]
    )
    taxonomy = metrics["failure_taxonomy"]
    if taxonomy:
        lines.extend(["| Failure type | Cases |", "| :-- | --: |"])
        lines.extend(f"| `{name}` | {count} |" for name, count in taxonomy.items())
    else:
        lines.append("No failures.")

    lines.extend(
        [
            "",
            "## Case summary",
            "",
            "| ID | Category | Expected | Actual | Retrieval | Citations | Facts | Safety | Result | Failures |",
            "| :-- | :-- | :-- | :-- | :--: | :--: | :--: | :--: | :--: | :-- |",
        ]
    )
    for result in report["cases"]:
        checks = result["checks"]
        lines.append(
            "| {id} | {category} | {expected} | {actual} | {retrieval} | {citation} | "
            "{facts} | {safety} | {status} | {failures} |".format(
                id=_cell(result["id"]),
                category=_cell(result["category"]),
                expected=result["expected_decision"],
                actual=result["actual_decision"],
                retrieval=_mark(checks["retrieval"]),
                citation=_mark(checks["citation_recall"] and checks["citation_integrity"]),
                facts=_mark(checks["facts"]),
                safety=_mark(checks["unsupported_claim_safety"]),
                status="PASS" if result["overall_pass"] else "FAIL",
                failures=_cell(", ".join(result["failure_types"]) or "—"),
            )
        )

    lines.extend(["", "## Full case results", ""])
    for result in report["cases"]:
        lines.extend(
            [
                f"### {result['id']} — {'PASS' if result['overall_pass'] else 'FAIL'}",
                "",
                result["question"],
                "",
                f"- Expected / actual: `{result['expected_decision']}` / `{result['actual_decision']}`",
                f"- Retrieved clauses: {_list_or_none(result['retrieved_clause_ids'])}",
                f"- Cited clauses: {_list_or_none(result['cited_clause_ids'])}",
                f"- Missing evidence: {_list_or_none(result['missing_evidence_clause_ids'])}",
                f"- Missing citations: {_list_or_none(result['missing_citation_clause_ids'])}",
                f"- Missing facts: {_list_or_none(result['missing_facts'])}",
                f"- Forbidden claims found: {_list_or_none(result['forbidden_claims_found'])}",
                f"- Failure taxonomy: {_list_or_none(result['failure_types'])}",
                "",
                f"#### Complete answer ({result['id']})",
                "",
                "```text",
                _answer_text(result),
                "```",
                "",
            ]
        )
        if result.get("error"):
            lines.extend(
                [
                    f"Error: `{result['error']['type']}: {result['error']['message']}`",
                    "",
                ]
            )
    lines.extend(
        [
            "## Method",
            "",
            "Every case exercised `GroundedAnswerPipeline.ask(..., include_trace=True)` with deterministic answer construction and reranking disabled. A case passes only when all recorded checks pass; retrieval-only success is insufficient.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _percent(value: float) -> str:
    return f"{value:.1%}"


def _state_result(metric: dict[str, Any]) -> str:
    return (
        f"{_percent(metric['decision_precision'])} / {_percent(metric['decision_recall'])} "
        f"({metric['decision_correct']} correct)"
    )


def _mark(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _markdown_requirement_lines(items: list[dict[str, Any]]) -> list[str]:
    lines = ["| Status | Requirement |", "| :-- | :-- |"]
    lines.extend(f"| {_mark(item['pass'])} | {_cell(item['name'])} |" for item in items)
    return lines


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _list_or_none(values: list[Any]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _answer_text(result: dict[str, Any]) -> str:
    response = result.get("response")
    if response:
        return str(response.get("answer", ""))
    error = result.get("error")
    return f"No answer returned ({error['type']}: {error['message']})." if error else "No answer returned."


if __name__ == "__main__":
    completed = run_evaluation()
    raise SystemExit(0 if completed["failures"] == 0 else 1)
