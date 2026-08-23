from __future__ import annotations

from pathlib import Path

from src.contradiction import ContradictionDetector
from src.models import EvidenceAssessment, SupportType


def direct(result, score: float = 0.9) -> EvidenceAssessment:
    return EvidenceAssessment(
        chunk_id=result.chunk.chunk_id,
        support_type=SupportType.DIRECT,
        explanation="direct test evidence",
        score=score,
        topic_coverage=score,
        answer_alignment=score,
    )


def test_curated_reporting_deadline_conflict_is_detected(
    chunks,
    findings_path: Path,
    make_result,
) -> None:
    wanted = {"4.3.2", "9.1.4"}
    retrieved = [make_result(chunk) for chunk in chunks if chunk.clause_id in wanted]

    findings = ContradictionDetector(findings_path).detect(
        "How many days do I have to report a change of circumstances?",
        retrieved,
        [direct(item) for item in retrieved],
    )

    assert len(findings) == 1
    assert findings[0].basis == "CURATED"
    assert set(findings[0].clause_ids) == wanted


def test_numeric_cross_reference_conflict_is_detected(make_chunk, make_result) -> None:
    ten_days = make_chunk(
        chunk_id="ten-days",
        clause_id="1.1.1",
        section_id="1.1",
        text="A recipient must report a change within 10 calendar days.",
    )
    thirty_days = make_chunk(
        chunk_id="thirty-days",
        clause_id="2.1.1",
        section_id="2.1",
        text="A recipient who reports the change within 30 calendar days complies with §1.1.",
        cross_references=["1.1"],
    )
    retrieved = [make_result(ten_days), make_result(thirty_days)]

    findings = ContradictionDetector().detect(
        "How many days may a recipient take to report a change?",
        retrieved,
        [direct(item) for item in retrieved],
    )

    assert len(findings) == 1
    assert findings[0].basis == "NUMERIC"


def test_28_to_90_day_extension_is_not_a_conflict(chunks, make_result) -> None:
    wanted = {"3.2.1", "3.2.2"}
    retrieved = [make_result(chunk) for chunk in chunks if chunk.clause_id in wanted]

    findings = ContradictionDetector().detect(
        "How long may a recipient be absent, including the medical extension?",
        retrieved,
        [direct(item) for item in retrieved],
    )

    assert findings == []


def test_unasked_neighbor_deadlines_do_not_create_a_numeric_conflict(
    chunks,
    make_result,
) -> None:
    wanted = {"4.3.2", "9.1.4"}
    retrieved = [make_result(chunk) for chunk in chunks if chunk.clause_id in wanted]

    findings = ContradictionDetector().detect(
        "Is an overpayment caused solely by Department error recoverable?",
        retrieved,
        [direct(item) for item in retrieved],
    )

    assert findings == []


def test_opposite_eligibility_polarity_is_detected(make_chunk, make_result) -> None:
    eligible = make_chunk(
        chunk_id="eligible",
        clause_id="1.1.1",
        section_id="1.1",
        text="Applicants resident in the county are eligible for assistance.",
    )
    ineligible = make_chunk(
        chunk_id="ineligible",
        clause_id="2.1.1",
        section_id="2.1",
        text="Applicants resident in the county are not eligible for assistance.",
    )
    retrieved = [make_result(eligible), make_result(ineligible)]

    findings = ContradictionDetector().detect(
        "Are applicants resident in the county eligible for assistance?",
        retrieved,
        [direct(item) for item in retrieved],
    )

    assert any(finding.basis == "POLARITY" for finding in findings)
