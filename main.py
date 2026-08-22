"""
The Grounded Answer — CLI Entry Point

Citation-aware RAG assistant for the Calder County HSP policy manual.

Usage:
    python main.py ingest                          Build the vector index
    python main.py ask "your question here"        Ask a policy question
    python main.py show-clause 4.3.2               Show a specific clause
    python main.py evaluate                        Run the evaluation suite
    python main.py interactive                     Interactive Q&A session
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Project root
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
INDEX_DIR = DATA_DIR / "faiss_index"
MANUAL_PATH = DATA_DIR / "policy-manual.md"


def cmd_ingest(args):
    """Parse the policy manual and build the FAISS index."""
    from src.parser import parse_policy_manual
    from src.embeddings import EmbeddingEngine
    from src.vector_store import VectorStore

    print("=" * 60)
    print("INGESTING POLICY MANUAL")
    print("=" * 60)

    # Parse
    print(f"\n📄 Parsing {MANUAL_PATH}...")
    clauses = parse_policy_manual(MANUAL_PATH)
    print(f"   Found {len(clauses)} clauses across {len(set(c.part for c in clauses))} parts.")

    # Embed
    print(f"\n🔤 Generating embeddings...")
    engine = EmbeddingEngine()
    embeddings = engine.encode_clauses(clauses)
    print(f"   Generated {embeddings.shape[0]} embeddings of dimension {embeddings.shape[1]}.")

    # Store
    print(f"\n💾 Building FAISS index...")
    store = VectorStore(dimension=engine.dimension)
    store.build(embeddings, clauses)
    store.save(INDEX_DIR)
    print(f"   Saved index to {INDEX_DIR}")

    print(f"\n✅ Ingestion complete. Ready to answer questions.")


def cmd_ask(args):
    """Ask a single policy question."""
    question = args.question
    if not question:
        print("Error: Please provide a question.")
        sys.exit(1)

    result = _ask_question(question, verbose=args.verbose)
    _print_result(result)


def cmd_show_clause(args):
    """Show a specific clause from the manual."""
    from src.parser import parse_policy_manual, format_clause_for_context

    clauses = parse_policy_manual(MANUAL_PATH)
    target = args.clause_id

    found = [c for c in clauses if c.clause_id == target]
    if not found:
        # Try partial match
        found = [c for c in clauses if c.clause_id.startswith(target)]

    if not found:
        print(f"Clause §{target} not found in the manual.")
        print(f"Available clause IDs: {', '.join(c.clause_id for c in clauses[:20])}...")
        sys.exit(1)

    for c in found:
        print("─" * 60)
        print(format_clause_for_context(c))
        print(f"\n{c.part}")
        print("─" * 60)


def cmd_interactive(args):
    """Interactive Q&A session."""
    print("=" * 60)
    print("THE GROUNDED ANSWER")
    print("Calder County Household Support Program Policy Assistant")
    print("=" * 60)
    print("\nType your question and press Enter. Type 'quit' to exit.\n")

    while True:
        try:
            question = input("❓ Question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        print()
        result = _ask_question(question, verbose=False)
        _print_result(result)
        print()


def cmd_evaluate(args):
    """Run the evaluation suite."""
    # Import here to avoid loading models unnecessarily
    eval_path = ROOT / "evaluation" / "evaluate.py"
    if not eval_path.exists():
        print("Evaluation suite not found. Create evaluation/evaluate.py first.")
        sys.exit(1)

    # Run evaluate.py as a module
    import importlib.util
    spec = importlib.util.spec_from_file_location("evaluate", eval_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run_evaluation()


def _load_components():
    """Load the retriever and generator (cached after first call)."""
    if not hasattr(_load_components, "_cache"):
        from src.embeddings import EmbeddingEngine
        from src.vector_store import VectorStore
        from src.retriever import Retriever
        from src.generator import AnswerGenerator

        if not INDEX_DIR.exists():
            print("Error: Index not found. Run 'python main.py ingest' first.")
            sys.exit(1)

        print("Loading models...", end=" ", flush=True)
        engine = EmbeddingEngine()

        store = VectorStore(dimension=engine.dimension)
        store.load(INDEX_DIR)

        retriever = Retriever(engine, store, use_reranker=True)

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("\n⚠ Warning: GEMINI_API_KEY not set. LLM answers will not be available.")
            generator = None
        else:
            generator = AnswerGenerator(api_key=api_key)

        print("done.")
        _load_components._cache = (retriever, generator)

    return _load_components._cache


def _ask_question(question: str, verbose: bool = False) -> dict:
    """Core question-answering pipeline."""
    from src.evidence import assess_evidence, AnswerState
    from src.refusal import generate_refusal
    from src.contradiction import generate_contradiction_response

    retriever, generator = _load_components()

    # Step 1: Retrieve relevant clauses
    start = time.time()
    results = retriever.retrieve(question)
    retrieval_time = time.time() - start

    if verbose:
        print(f"\n📊 Retrieved {len(results)} clauses in {retrieval_time:.2f}s:")
        for r in results:
            print(f"   §{r.clause.clause_id} (score: {r.final_score:.3f})")

    # Step 2: Assess evidence
    llm_conflict_checker = None
    if generator is not None:
        llm_conflict_checker = generator.check_conflict

    assessment = assess_evidence(question, results, llm_conflict_checker=llm_conflict_checker)

    if verbose:
        print(f"\n📋 Evidence assessment: {assessment.state.value}")
        print(f"   Reason: {assessment.reason}")

    # Step 3: Generate appropriate response
    if assessment.state == AnswerState.REFUSE:
        result = generate_refusal(question, assessment)
    elif assessment.state == AnswerState.CONFLICT:
        result = generate_contradiction_response(question, assessment)
    elif assessment.state == AnswerState.ANSWER:
        if generator is None:
            # Fallback: show clauses without LLM synthesis
            result = _fallback_answer(assessment)
        else:
            start = time.time()
            result = generator.generate_answer(question, assessment)
            result["generation_time"] = time.time() - start
    else:
        result = generate_refusal(question, assessment)

    result["retrieval_time"] = retrieval_time
    result["question"] = question
    return result


def _fallback_answer(assessment) -> dict:
    """Generate a response without the LLM, showing raw clauses."""
    from src.parser import format_clause_for_context

    parts = ["The following clauses appear relevant to your question:\n"]
    citations = []
    for r in assessment.supporting_results:
        parts.append(format_clause_for_context(r.clause))
        parts.append("")
        citations.append({
            "clause_id": r.clause.clause_id,
            "section": r.clause.section,
            "part": r.clause.part,
            "lines": f"{r.clause.line_start}-{r.clause.line_end}",
            "score": round(r.final_score, 3),
        })

    return {
        "answer": "\n".join(parts),
        "state": "answer",
        "citations": citations,
        "top_score": assessment.top_score,
        "note": "LLM not available — showing raw clause text.",
    }


def _print_result(result: dict):
    """Pretty-print a response to the terminal."""
    state = result.get("state", "unknown")

    if state == "answer":
        print("─" * 60)
        print("✅ ANSWER")
        print("─" * 60)
        print(result["answer"])

        if result.get("citations"):
            print("\n📑 SOURCES:")
            for c in result["citations"]:
                print(f"   §{c['clause_id']} — {c.get('section', '')} (lines {c.get('lines', '?')})")

        if result.get("warnings"):
            print("\n⚠ WARNINGS:")
            for w in result["warnings"]:
                print(f"   {w}")

    elif state == "conflict":
        print("─" * 60)
        print("⚠ MANUAL CONFLICT")
        print("─" * 60)
        print(result["answer"])

        if result.get("citations"):
            print("\n📑 SOURCES:")
            for c in result["citations"]:
                print(f"   §{c['clause_id']} — {c.get('section', '')} (lines {c.get('lines', '?')})")

    elif state == "refuse":
        print("─" * 60)
        print("🚫 UNABLE TO ANSWER")
        print("─" * 60)
        print(result["answer"])

    else:
        print(result.get("answer", "Unknown error."))

    # Timing info
    times = []
    if "retrieval_time" in result:
        times.append(f"retrieval: {result['retrieval_time']:.2f}s")
    if "generation_time" in result:
        times.append(f"generation: {result['generation_time']:.2f}s")
    if times:
        print(f"\n⏱ {', '.join(times)}")


def main():
    parser = argparse.ArgumentParser(
        description="The Grounded Answer — Policy Manual RAG Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ingest
    sub_ingest = subparsers.add_parser("ingest", help="Parse the manual and build the vector index")

    # ask
    sub_ask = subparsers.add_parser("ask", help="Ask a policy question")
    sub_ask.add_argument("question", type=str, help="The question to ask")
    sub_ask.add_argument("-v", "--verbose", action="store_true", help="Show retrieval details")

    # show-clause
    sub_show = subparsers.add_parser("show-clause", help="Display a specific policy clause")
    sub_show.add_argument("clause_id", type=str, help="Clause ID (e.g. 4.3.2)")

    # interactive
    sub_interactive = subparsers.add_parser("interactive", help="Interactive Q&A session")

    # evaluate
    sub_eval = subparsers.add_parser("evaluate", help="Run the evaluation suite")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "ingest": cmd_ingest,
        "ask": cmd_ask,
        "show-clause": cmd_show_clause,
        "interactive": cmd_interactive,
        "evaluate": cmd_evaluate,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
