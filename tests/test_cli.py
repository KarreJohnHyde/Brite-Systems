from __future__ import annotations

import json
from pathlib import Path

import pytest

import main as cli


@pytest.fixture
def cli_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    corpus_path: Path,
    findings_path: Path,
    contacts_path: Path,
) -> dict[str, Path]:
    paths = {
        "processed": tmp_path / "processed" / "chunks.json",
        "report": tmp_path / "processed" / "corpus-report.json",
        "index": tmp_path / "indexes",
    }
    values = {
        "CORPUS_PATH": corpus_path,
        "PROCESSED_PATH": paths["processed"],
        "CORPUS_REPORT_PATH": paths["report"],
        "INDEX_DIR": paths["index"],
        "POLICY_FINDINGS_PATH": findings_path,
        "CONTACTS_PATH": contacts_path,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv("AMENDMENT_PATH", "off")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "128")
    monkeypatch.setenv("ENABLE_RERANKING", "false")
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    return paths


def test_cli_parser_exposes_required_commands() -> None:
    parser = cli.build_parser()

    for argv, command in [
        (["ingest"], "ingest"),
        (["ask", "question"], "ask"),
        (["source", "2.4.1"], "source"),
        (["corpus-report"], "corpus-report"),
        (["evaluate"], "evaluate"),
        (["calibrate"], "calibrate"),
    ]:
        assert parser.parse_args(argv).command == command

    custom_evaluation = parser.parse_args(
        ["evaluate", "--questions", "evaluation/adversarial_questions.json", "--output-dir", "out"]
    )
    assert custom_evaluation.questions == Path("evaluation/adversarial_questions.json")
    assert custom_evaluation.output_dir == Path("out")

    reranked_evaluation = parser.parse_args(["evaluate", "--respect-reranking"])
    assert reranked_evaluation.respect_reranking is True


def test_cli_corpus_report_is_valid_json(corpus_path: Path, capsys) -> None:
    exit_code = cli.main(["corpus-report", "--corpus", str(corpus_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["clauses"] == 148
    assert payload["pages"] is None
    assert captured.err == ""


def test_cli_source_outputs_exact_source_without_index(
    cli_environment,
    corpus_path: Path,
    capsys,
) -> None:
    exit_code = cli.main(
        ["source", "2.4.1", "--corpus", str(corpus_path), "--json"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload[0]["clause_id"] == "2.4.1"
    assert payload[0]["source_text"].startswith("**2.4.1**")


def test_cli_ingest_then_ask_offline(
    cli_environment,
    corpus_path: Path,
    capsys,
) -> None:
    ingest_code = cli.main(
        ["ingest", "--corpus", str(corpus_path), "--embedding-backend", "hashing"]
    )
    ingest_output = capsys.readouterr()

    assert ingest_code == 0
    assert "Corpus indexed successfully" in ingest_output.out
    assert "Clauses / chunks:  148 / 148" in ingest_output.out

    ask_code = cli.main(
        [
            "ask",
            "What is the household resource limit?",
            "--embedding-backend",
            "hashing",
            "--json",
        ]
    )
    ask_output = capsys.readouterr()
    try:
        payload = json.loads(ask_output.out)
    except json.JSONDecodeError:
        print(f'ask_code: {ask_code}\nout: {ask_output.out}\nerr: {ask_output.err}')
        raise

    assert ask_code == 0
    assert payload["decision"] == "ANSWER"
    assert payload["citations"][0]["clause_id"] == "2.4.1"
    assert "$4,000" in payload["answer"]


def test_cli_missing_index_returns_clear_error(cli_environment, capsys) -> None:
    exit_code = cli.main(
        ["ask", "What is the resource limit?", "--embedding-backend", "hashing"]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Policy index not found" in captured.err


def test_cli_unknown_source_returns_nonzero(cli_environment, corpus_path: Path, capsys) -> None:
    exit_code = cli.main(
        ["source", "does-not-exist", "--corpus", str(corpus_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "No source found" in captured.err
