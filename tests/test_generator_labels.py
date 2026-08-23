from __future__ import annotations

from src.generator import AnswerBuilder
from src.models import ConflictFinding, Decision, DecisionTrace, RetrievedClause


def test_conflict_answer_uses_amendment_locator_instead_of_none(
    make_chunk,
    project_root,
) -> None:
    manual = make_chunk(
        chunk_id="chunk_manual",
        clause_id="4.3.2",
        text="A change must be reported within 10 calendar days.",
    )
    amendment = make_chunk(
        chunk_id="chunk_amendment",
        clause_id="2.1.1",
        text="For 10 calendar days substitute 14 calendar days.",
    ).model_copy(
        update={
            "clause_id": None,
            "source_kind": "amendment",
            "locator_kind": "paragraph",
            "source_locator": "amendment-2026-01:2.1",
            "source_locator_label": "Amendment No. 2026-01 ¶2.1",
        }
    )
    finding = ConflictFinding(
        finding_id="test-conflict",
        chunk_ids=[manual.chunk_id, amendment.chunk_id],
        clause_ids=["4.3.2", "amendment-2026-01:2.1"],
        explanation="The provisions conflict.",
        basis="CURATED",
        confidence=1.0,
    )
    trace = DecisionTrace(
        question="Which reporting period applies?",
        retrieved=[RetrievedClause(chunk=manual), RetrievedClause(chunk=amendment)],
        conflicts=[finding],
        decision=Decision.CONFLICT,
        decision_reason="The provisions conflict.",
        refusal_threshold=0.58,
    )
    builder = AnswerBuilder(
        contacts_path=project_root / "data" / "contacts.json",
        findings_path=project_root / "data" / "policy_findings.json",
    )

    answer = builder.build(trace)

    assert "Amendment No. 2026-01 ¶2.1" in answer.answer
    assert "§None" not in answer.answer
