"""Command-line interface for The Grounded Answer.

Examples:
    python main.py ingest
    python main.py ask "What is the household resource limit?"
    python main.py source 2.4.1
    python main.py evaluate
    python main.py calibrate
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

from config.settings import Settings
from src.models import PolicyAnswer
from src.parser import (
    build_combined_corpus_report,
    build_corpus_report,
    find_chunks,
    parse_policy_manual,
    parse_policy_sources,
)
from src.pipeline import GroundedAnswerPipeline, ingest_corpus, load_source_chunks


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; use YYYY-MM-DD"
        ) from exc


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.from_env(
        corpus_path=getattr(args, "corpus", None),
        amendment_path=getattr(args, "amendment", None),
        embedding_backend=getattr(args, "embedding_backend", None),
        llm_provider=getattr(args, "provider", None),
    )


def _configure_logging(settings: Settings, debug: bool = False) -> None:
    level = logging.DEBUG if debug else getattr(logging, settings.log_level, logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _configure_logging(settings)
    report, manifest = ingest_corpus(settings)
    print("Corpus indexed successfully")
    print()
    if hasattr(report, "documents"):
        print(f"Documents:         {report.documents}")
        print(f"Combined SHA-256:   {report.combined_source_sha256}")
        print("Parts:             n/a (multiple sources)")
        print("Sections:          n/a (multiple sources)")
    else:
        print(f"Document:          {report.document_name}")
        print(f"Version:           {report.document_version or 'not stated'}")
        print(f"Source SHA-256:     {report.source_sha256}")
        print(f"Parts:             {report.parts}")
        print(f"Sections:          {report.sections}")
    print(f"Clauses / chunks:  {report.clauses} / {report.chunks}")
    print("Pages:             unavailable in the Markdown source")
    print(f"Embedding backend: {manifest['embedding_backend']}")
    print(f"Embedding model:   {manifest['embedding_model']}")
    print(f"Vector dimension:  {manifest['dimension']}")
    print(f"Index:             {settings.index_dir}")
    print(f"Corpus report:     {settings.corpus_report_path}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _configure_logging(settings, args.debug)
    pipeline = GroundedAnswerPipeline.load(settings)
    try:
        answer = pipeline.ask(
            args.question,
            include_trace=args.debug,
            change_date=args.change_date,
            determination_date=args.determination_date,
        )
        if args.json:
            print(answer.model_dump_json(indent=2))
        else:
            print_policy_answer(answer, debug=args.debug)
    finally:
        pipeline.flush_traces()
    return 0


def print_policy_answer(answer: PolicyAnswer, *, debug: bool = False) -> None:
    print(f"STATUS: {answer.decision.value}")
    print()
    print(answer.answer)
    if answer.reason:
        print()
        print("WHY")
        print(answer.reason)
    if answer.next_step:
        print()
        print("NEXT STEP")
        print(answer.next_step)
    if answer.citations:
        print()
        print("SOURCES")
        for citation in answer.citations:
            label = (
                citation.source_locator_label
                or (f"Policy Manual §{citation.clause_id}" if citation.clause_id else None)
                or citation.source_locator
                or citation.chunk_id
            )
            location = f"lines {citation.line_start}-{citation.line_end}"
            if citation.page is not None:
                location = f"page {citation.page}; {location}"
            title = citation.section_title or citation.document_title or "Untitled source"
            print(f"{label} — {title} ({location})")
            print(f'"{citation.excerpt}"')
            print()
    print(f"Evidence: {answer.evidence_level.value}")
    if debug and answer.trace:
        print()
        print("DEBUG TRACE")
        print(answer.trace.model_dump_json(indent=2))


def cmd_source(args: argparse.Namespace) -> int:
    settings = _settings(args)
    chunks = load_source_chunks(settings)
    matches = find_chunks(chunks, args.source_id)
    if not matches:
        print(f"No source found for {args.source_id!r}.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([chunk.model_dump(mode="json") for chunk in matches], indent=2, ensure_ascii=False))
        return 0
    for index, chunk in enumerate(matches):
        if index:
            print()
        label = (
            chunk.source_locator_label
            or (f"Policy Manual §{chunk.clause_id}" if chunk.clause_id else None)
            or chunk.source_locator
            or chunk.chunk_id
        )
        print(f"{label} — {chunk.section_id} {chunk.section_title}")
        print(f"Document: {chunk.document_name} ({chunk.document_version or 'version not stated'})")
        print(f"Page: unavailable | Lines: {chunk.line_start}-{chunk.line_end}")
        print()
        print("FULL SOURCE TEXT")
        print(chunk.source_text)
    return 0


def cmd_corpus_report(args: argparse.Namespace) -> int:
    settings = _settings(args)
    paths = settings.source_paths
    if len(paths) == 1:
        chunks = parse_policy_manual(paths[0])
        report = build_corpus_report(paths[0], chunks)
    else:
        chunks = parse_policy_sources(paths[0], paths[1:])
        report = build_combined_corpus_report(paths, chunks)
    print(report.model_dump_json(indent=2))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _configure_logging(settings)
    from evaluation.evaluate import run_evaluation

    report = run_evaluation(
        settings=settings,
        quiet=args.quiet,
        questions_path=args.questions,
        output_dir=args.output_dir,
        respect_reranking=args.respect_reranking,
    )
    return 0 if report["failures"] == 0 else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _configure_logging(settings)
    from evaluation.calibration import run_calibration

    run_calibration(settings=settings)
    return 0


def cmd_interactive(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _configure_logging(settings)
    pipeline = GroundedAnswerPipeline.load(settings)
    print("THE GROUNDED ANSWER")
    print("Policy-grounded decision support. Type 'quit' to exit.")
    try:
        while True:
            try:
                question = input("\nQuestion: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if question.lower() in {"quit", "exit", "q"}:
                return 0
            if not question:
                continue
            print()
            print_policy_answer(pipeline.ask(question))
    finally:
        pipeline.flush_traces()


@lru_cache(maxsize=4)
def _cached_pipeline(backend: str = "hashing", provider: str = "deterministic") -> GroundedAnswerPipeline:
    settings = Settings.from_env(embedding_backend=backend, llm_provider=provider)
    return GroundedAnswerPipeline.load(settings)


def _ask_question(question: str, verbose: bool = False) -> dict:
    """Compatibility adapter used by the optional Streamlit application."""

    answer = _cached_pipeline().ask(question, include_trace=verbose)
    payload = answer.model_dump(mode="json")
    payload["state"] = answer.decision.value.lower()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Citation-aware, refusal-calibrated policy evidence assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Parse the real corpus and build the policy index")
    ingest.add_argument("--corpus", type=Path, help="Path to the supplied Markdown corpus")
    ingest.add_argument(
        "--amendment",
        type=Path,
        help="Optional amendment paired with an explicitly supplied manual",
    )
    ingest.add_argument(
        "--embedding-backend",
        choices=("hashing", "sentence-transformers"),
        help="Dense embedding backend (default: environment or hashing)",
    )
    ingest.set_defaults(func=cmd_ingest)

    ask = commands.add_parser("ask", help="Ask one plain-language policy question")
    ask.add_argument("question")
    ask.add_argument("--corpus", type=Path, help=argparse.SUPPRESS)
    ask.add_argument("--amendment", type=Path, help=argparse.SUPPRESS)
    ask.add_argument("--embedding-backend", choices=("hashing", "sentence-transformers"))
    ask.add_argument("--provider", choices=("deterministic", "gemini"))
    ask.add_argument(
        "--change-date",
        type=_iso_date,
        metavar="YYYY-MM-DD",
        help="Date the change of circumstances occurred",
    )
    ask.add_argument(
        "--determination-date",
        type=_iso_date,
        metavar="YYYY-MM-DD",
        help="Date the policy determination was made",
    )
    ask.add_argument("--debug", action="store_true", help="Show retrieval/evidence/decision trace")
    ask.add_argument("--json", action="store_true", help="Emit the validated response as JSON")
    ask.set_defaults(func=cmd_ask)

    source = commands.add_parser("source", aliases=["show-clause"], help="Show exact source text")
    source.add_argument("source_id", help="Opaque chunk ID, official clause ID, or section ID")
    source.add_argument("--corpus", type=Path, help=argparse.SUPPRESS)
    source.add_argument("--amendment", type=Path, help=argparse.SUPPRESS)
    source.add_argument("--json", action="store_true")
    source.set_defaults(func=cmd_source)

    report = commands.add_parser("corpus-report", help="Inspect corpus structure without indexing")
    report.add_argument("--corpus", type=Path)
    report.add_argument("--amendment", type=Path)
    report.set_defaults(func=cmd_corpus_report)

    evaluate = commands.add_parser("evaluate", help="Run the source-derived evaluation set")
    evaluate.add_argument("--quiet", action="store_true", help="Print only summary and failures")
    evaluate.add_argument("--questions", type=Path, help="Optional labeled question-set JSON")
    evaluate.add_argument("--output-dir", type=Path, help="Directory for JSON and Markdown results")
    evaluate.add_argument("--embedding-backend", choices=("hashing", "sentence-transformers"))
    evaluate.add_argument(
        "--respect-reranking",
        action="store_true",
        help="Use configured reranking instead of the default reranker-off evaluation",
    )
    evaluate.set_defaults(func=cmd_evaluate)

    calibrate = commands.add_parser("calibrate", help="Sweep support thresholds over the evaluation set")
    calibrate.add_argument("--embedding-backend", choices=("hashing", "sentence-transformers"))
    calibrate.set_defaults(func=cmd_calibrate)

    interactive = commands.add_parser("interactive", help="Ask multiple independent questions")
    interactive.add_argument("--embedding-backend", choices=("hashing", "sentence-transformers"))
    interactive.set_defaults(func=cmd_interactive)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
