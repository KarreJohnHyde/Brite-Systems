from __future__ import annotations

from pathlib import Path

import pytest

from src.parser import (
    CorpusParseError,
    build_corpus_report,
    load_chunks,
    parse_policy_manual,
    persist_chunks,
)


def by_clause(chunks, clause_id: str):
    return next(chunk for chunk in chunks if chunk.clause_id == clause_id)


def test_real_corpus_structure_and_page_null(corpus_path: Path, chunks) -> None:
    report = build_corpus_report(corpus_path, chunks)

    assert len(chunks) == 148
    assert report.clauses == 148
    assert report.chunks == 148
    assert report.parts == 12
    assert report.sections == 54
    assert report.pages is None
    assert all(chunk.page is None for chunk in chunks)
    assert chunks[0].document_version == "31 December 2025"
    assert chunks[0].effective_date == "2025-12-31"
    assert [chunk.source_order for chunk in chunks] == list(range(148))
    assert len({chunk.chunk_id for chunk in chunks}) == 148


def test_every_chunk_round_trips_exact_utf8_byte_offsets(corpus_path: Path, chunks) -> None:
    source = corpus_path.read_bytes()

    for chunk in chunks:
        exact = source[chunk.start_offset : chunk.end_offset].decode("utf-8")
        assert exact == chunk.source_text
        assert exact.startswith(f"**{chunk.clause_id}")
        assert chunk.start_offset < chunk.end_offset


def test_ingestion_is_deterministic(corpus_path: Path, chunks) -> None:
    second_parse = parse_policy_manual(corpus_path)

    first_identity = [
        (chunk.chunk_id, chunk.start_offset, chunk.end_offset, chunk.source_text)
        for chunk in chunks
    ]
    second_identity = [
        (chunk.chunk_id, chunk.start_offset, chunk.end_offset, chunk.source_text)
        for chunk in second_parse
    ]
    assert second_identity == first_identity


def test_table_and_subitems_remain_inside_their_clauses(chunks) -> None:
    eligibility = by_clause(chunks, "2.1.2")
    thresholds = by_clause(chunks, "6.6.1")

    assert "(a) is resident in Calder County" in eligibility.source_text
    assert "(f) has made a valid application" in eligibility.raw_text
    assert eligibility.line_start == 72
    assert eligibility.line_end == 84

    assert "| Household size | Monthly threshold |" in thresholds.source_text
    assert "| each additional member | + $410 |" in thresholds.raw_text
    assert "**$" not in thresholds.text


def test_definition_display_does_not_duplicate_source_dash(chunks) -> None:
    applicant = by_clause(chunks, "1.4.1")

    assert applicant.source_text.startswith("**1.4.1 Applicant** — a person")
    assert applicant.raw_text.startswith("Applicant — a person")
    assert "— —" not in applicant.text


def test_persisted_chunks_round_trip_without_metadata_loss(
    tmp_path: Path,
    corpus_path: Path,
    chunks,
) -> None:
    chunks_path = tmp_path / "processed" / "chunks.json"
    report_path = tmp_path / "processed" / "report.json"
    report = build_corpus_report(corpus_path, chunks)

    persist_chunks(chunks, report, chunks_path, report_path)
    loaded = load_chunks(chunks_path)

    assert loaded == chunks
    assert report_path.exists()


def test_duplicate_official_clause_ids_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.md"
    source.write_text(
        "# Part 1 — Test\n\n## 1.1 Rules\n\n"
        "**1.1.1** First rule.\n\n**1.1.1** Duplicate rule.\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusParseError, match="Duplicate official clause ID"):
        parse_policy_manual(source)


def test_missing_clause_structure_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "empty.md"
    source.write_text("# A document without numbered policy clauses\n", encoding="utf-8")

    with pytest.raises(CorpusParseError, match="No official clauses"):
        parse_policy_manual(source)
