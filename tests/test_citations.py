from __future__ import annotations

import pytest

from src.citations import (
    CitationIntegrityError,
    CitationValidator,
    validate_citations,
)


def test_citation_is_built_only_from_trusted_retrieved_metadata(chunks, make_result) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")
    validator = CitationValidator([make_result(chunk)])

    citation = validator.build([chunk.chunk_id])[0]

    assert citation.chunk_id == chunk.chunk_id
    assert citation.clause_id == "2.4.1"
    assert citation.page is None
    assert citation.excerpt == chunk.text
    assert (citation.line_start, citation.line_end) == (chunk.line_start, chunk.line_end)


def test_forged_source_id_is_rejected(chunks, make_result) -> None:
    chunk = chunks[0]
    validator = CitationValidator([make_result(chunk)])

    with pytest.raises(CitationIntegrityError, match="fabricated source IDs"):
        validator.build(["chunk_forged"])


def test_real_but_unretrieved_source_id_is_rejected(chunks, make_result) -> None:
    retrieved, unretrieved = chunks[0], chunks[1]
    validator = CitationValidator([make_result(retrieved)])

    with pytest.raises(CitationIntegrityError, match="Unretrieved"):
        validator.build([unretrieved.chunk_id])


def test_missing_supporting_source_is_rejected(chunks, make_result) -> None:
    validator = CitationValidator([make_result(chunks[0])])

    with pytest.raises(CitationIntegrityError, match="No supporting source IDs"):
        validator.build([])


def test_invented_numeric_claim_is_rejected(chunks, make_result) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")
    validator = CitationValidator([make_result(chunk)])

    with pytest.raises(CitationIntegrityError, match="introduced values"):
        validator.validate_claims(
            "The household resource limit is $99,999 under §2.4.1.",
            [chunk.chunk_id],
        )


def test_invented_clause_reference_is_rejected(chunks, make_result) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")
    validator = CitationValidator([make_result(chunk)])

    with pytest.raises(CitationIntegrityError):
        validator.validate_claims(
            "The household resource rule appears in §9.9.9 and is $4,000.",
            [chunk.chunk_id],
        )


def test_off_source_generated_claim_is_rejected(chunks, make_result) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")
    validator = CitationValidator([make_result(chunk)])

    with pytest.raises(CitationIntegrityError, match="insufficient lexical support"):
        validator.validate_claims(
            "Astronauts receive unlimited lunar cheese deliveries.",
            [chunk.chunk_id],
        )


def test_grounded_claim_with_exact_value_passes(chunks, make_result) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")
    validator = CitationValidator([make_result(chunk)])

    validator.validate_claims(
        "The household is not eligible where total countable resources exceed $4,000.",
        [chunk.chunk_id],
    )


def test_valid_inline_clause_reference_is_not_mistaken_for_an_invented_value(
    chunks,
    make_result,
) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")
    validator = CitationValidator([make_result(chunk)])

    validator.validate_claims(
        "The household is not eligible where total countable resources exceed $4,000 under §2.4.1.",
        [chunk.chunk_id],
    )


def test_compatibility_validator_does_not_accept_section_level_citation(chunks) -> None:
    chunk = next(item for item in chunks if item.clause_id == "2.4.1")

    valid, invalid = validate_citations(["2.4", "2.4.1"], [chunk])

    assert valid == ["2.4.1"]
    assert invalid == ["2.4"]
