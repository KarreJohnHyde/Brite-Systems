"""
Evaluation suite for The Grounded Answer.

Runs the 10-question test set through the full pipeline and reports
pass/fail results with detailed analysis.
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def run_evaluation():
    """Run all test questions and generate a results report."""
    from src.embeddings import EmbeddingEngine
    from src.vector_store import VectorStore
    from src.retriever import Retriever
    from src.evidence import assess_evidence, AnswerState
    from src.refusal import generate_refusal
    from src.contradiction import generate_contradiction_response
    from src.generator import AnswerGenerator

    # Load test questions
    questions_path = ROOT / "evaluation" / "questions.json"
    with open(questions_path, "r", encoding="utf-8") as f:
        test_questions = json.load(f)

    # Load components
    index_dir = ROOT / "data" / "faiss_index"
    if not index_dir.exists():
        print("Error: Index not found. Run 'python main.py ingest' first.")
        return

    print("Loading models...", end=" ", flush=True)
    engine = EmbeddingEngine()
    store = VectorStore(dimension=engine.dimension)
    store.load(index_dir)
    retriever = Retriever(engine, store, use_reranker=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    generator = AnswerGenerator(api_key=api_key) if api_key else None
    print("done.\n")

    # Run evaluation
    print("=" * 70)
    print("EVALUATION SUITE — The Grounded Answer")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Questions: {len(test_questions)}")
    print("=" * 70)

    results = []
    passes = 0
    failures = 0

    for tq in test_questions:
        qid = tq["id"]
        question = tq["question"]
        expected_state = tq["expected_state"]
        expected_clauses = tq.get("expected_clauses", [])

        print(f"\n{'─' * 70}")
        print(f"[{qid}] {question}")
        print(f"  Expected: state={expected_state}, clauses={expected_clauses}")

        # Run retrieval
        start = time.time()
        retrieval_results = retriever.retrieve(question)
        retrieval_time = time.time() - start

        # Run evidence assessment
        llm_checker = generator.check_conflict if generator else None
        assessment = assess_evidence(question, retrieval_results, llm_conflict_checker=llm_checker)

        actual_state = assessment.state.value
        top_score = assessment.top_score

        # Get retrieved clause IDs
        retrieved_ids = [r.clause.clause_id for r in retrieval_results]
        supporting_ids = [r.clause.clause_id for r in assessment.supporting_results]

        # Check state match
        state_pass = actual_state == expected_state

        # Check clause match (for ANSWER and CONFLICT states)
        clause_pass = True
        missing_clauses = []
        if expected_clauses and expected_state != "refuse":
            for ec in expected_clauses:
                if ec not in retrieved_ids and ec not in supporting_ids:
                    clause_pass = False
                    missing_clauses.append(ec)

        overall_pass = state_pass and clause_pass

        if overall_pass:
            passes += 1
            status = "✅ PASS"
        else:
            failures += 1
            status = "❌ FAIL"

        print(f"  Actual:   state={actual_state}, top_score={top_score:.3f}")
        print(f"  Retrieved: {retrieved_ids[:5]}")
        print(f"  Status:   {status}")

        if not state_pass:
            print(f"  ⚠ State mismatch: expected {expected_state}, got {actual_state}")
        if missing_clauses:
            print(f"  ⚠ Missing clauses: {missing_clauses}")

        # Generate the actual response for the report
        response_text = ""
        if assessment.state == AnswerState.REFUSE:
            resp = generate_refusal(question, assessment)
            response_text = resp["answer"]
        elif assessment.state == AnswerState.CONFLICT:
            resp = generate_contradiction_response(question, assessment)
            response_text = resp["answer"]
        elif assessment.state == AnswerState.ANSWER and generator:
            try:
                resp = generator.generate_answer(question, assessment)
                response_text = resp["answer"]
            except Exception as e:
                response_text = f"(LLM error: {e})"
        else:
            response_text = "(No LLM available for answer generation)"

        results.append({
            "id": qid,
            "question": question,
            "expected_state": expected_state,
            "expected_clauses": expected_clauses,
            "actual_state": actual_state,
            "top_score": round(top_score, 3),
            "retrieved_ids": retrieved_ids[:5],
            "supporting_ids": supporting_ids,
            "state_pass": state_pass,
            "clause_pass": clause_pass,
            "overall_pass": overall_pass,
            "missing_clauses": missing_clauses,
            "response_preview": response_text[:300],
            "retrieval_time": round(retrieval_time, 3),
            "notes": tq.get("notes", ""),
        })

    # Summary
    total = len(test_questions)
    print(f"\n{'=' * 70}")
    print(f"RESULTS: {passes}/{total} passed, {failures}/{total} failed")
    print(f"{'=' * 70}")

    # Generate markdown report
    _generate_report(results, passes, failures, total)


def _generate_report(results, passes, failures, total):
    """Generate a markdown evaluation report."""
    report_path = ROOT / "evaluation" / "results.md"

    lines = [
        "# Evaluation Results — The Grounded Answer",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total questions**: {total}",
        f"**Passed**: {passes}",
        f"**Failed**: {failures}",
        f"**Pass rate**: {passes/total*100:.0f}%",
        "",
        "## Summary Table",
        "",
        "| ID | Question | Expected | Actual | Score | Pass |",
        "|:--|:--|:--|:--|:--|:--|",
    ]

    for r in results:
        status = "✅" if r["overall_pass"] else "❌"
        lines.append(
            f"| {r['id']} | {r['question'][:50]}... | {r['expected_state']} "
            f"| {r['actual_state']} | {r['top_score']} | {status} |"
        )

    lines.extend(["", "## Detailed Results", ""])

    for r in results:
        status = "✅ PASS" if r["overall_pass"] else "❌ FAIL"
        lines.extend([
            f"### [{r['id']}] {r['question']}",
            "",
            f"- **Expected state**: {r['expected_state']}",
            f"- **Actual state**: {r['actual_state']}",
            f"- **Top retrieval score**: {r['top_score']}",
            f"- **Retrieved clauses**: {', '.join(r['retrieved_ids'])}",
            f"- **Result**: {status}",
            "",
        ])

        if r["missing_clauses"]:
            lines.append(f"- **Missing clauses**: {', '.join(r['missing_clauses'])}")
            lines.append("")

        if r["notes"]:
            lines.append(f"> {r['notes']}")
            lines.append("")

        lines.extend([
            "**Response preview**:",
            "```",
            r["response_preview"],
            "```",
            "",
        ])

    # Analysis section
    lines.extend([
        "## Analysis",
        "",
        "### What worked",
        "",
    ])

    passed = [r for r in results if r["overall_pass"]]
    failed = [r for r in results if not r["overall_pass"]]

    if passed:
        for r in passed:
            lines.append(f"- **{r['id']}**: Correctly produced `{r['actual_state']}` state")

    lines.extend(["", "### What failed", ""])

    if failed:
        for r in failed:
            lines.append(
                f"- **{r['id']}**: Expected `{r['expected_state']}` but got `{r['actual_state']}`. "
                f"{'Missing clauses: ' + ', '.join(r['missing_clauses']) if r['missing_clauses'] else ''}"
            )
    else:
        lines.append("All questions passed.")

    lines.extend([
        "",
        "### Threshold calibration",
        "",
        f"The current relevance threshold is set at the value defined in `src/evidence.py`.",
        "See DECISIONS.md for the rationale behind this threshold.",
        "",
    ])

    report_text = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n📄 Full report saved to: {report_path}")


if __name__ == "__main__":
    run_evaluation()
