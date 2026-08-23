from __future__ import annotations

import pytest

from config.settings import Settings
from evaluation.metrics import load_questions, validate_question_clause_ids
from src.embeddings import EmbeddingEngine
from src.models import Decision
from src.parser import parse_policy_sources, source_bundle_sha256
from src.pipeline import GroundedAnswerPipeline
from src.vector_store import VectorStore


@pytest.fixture(scope="module")
def temporal_pipeline(project_root):
    corpus_path = project_root / "data" / "policy-manual.md"
    amendment_path = project_root / "data" / "amendment-2026-01.md"
    chunks = parse_policy_sources(corpus_path, [amendment_path])
    engine = EmbeddingEngine(backend="hashing", dimension=256)
    store = VectorStore(engine.dimension)
    store.build(
        engine.encode_clauses(chunks),
        chunks,
        embedding_backend=engine.backend,
        embedding_model=engine.model_name,
        corpus_sha256=source_bundle_sha256((corpus_path, amendment_path)),
    )
    settings = Settings(
        project_root=project_root,
        corpus_path=corpus_path,
        amendment_path=amendment_path,
        timeline_path=project_root / "data" / "policy_timeline.json",
        findings_path=project_root / "data" / "policy_findings.json",
        contacts_path=project_root / "data" / "contacts.json",
        embedding_backend="hashing",
        embedding_dimension=256,
        enable_hybrid_search=True,
        enable_reranking=False,
        enable_neighbor_retrieval=True,
        llm_provider="deterministic",
    )
    return GroundedAnswerPipeline(settings, engine, store)


def test_amended_earnings_disregard_uses_determination_date(temporal_pipeline) -> None:
    before = temporal_pipeline.ask("What is the earnings disregard for a claim date February 2026?")
    after = temporal_pipeline.ask("What is the earnings disregard for a claim date April 2026?")

    assert before.decision == Decision.ANSWER
    assert "$120" in before.answer
    assert "$175" not in before.answer.split("standard disregards are:", 1)[-1].split(";", 1)[0]
    assert after.decision == Decision.ANSWER
    assert "$175" in after.answer
    assert {"6.4.1", None} <= {citation.clause_id for citation in after.citations}
    assert "Amendment No. 2026-01 ¶1.1" in {
        citation.source_locator_label for citation in after.citations
    }


def test_reporting_deadline_uses_change_date_transition(temporal_pipeline) -> None:
    pre = temporal_pipeline.ask(
        "How many days do I have to report a change that happened on 15 February 2026?"
    )
    post = temporal_pipeline.ask(
        "How many days do I have to report a change that happened on 15 March 2026?"
    )

    assert pre.decision == Decision.CONFLICT
    assert "10 calendar days" in pre.answer
    assert "30 calendar days" in pre.answer
    assert post.decision == Decision.ANSWER
    assert "14-calendar-day" in post.answer
    assert "Amendment No. 2026-01 ¶5.2" in {
        citation.source_locator_label for citation in post.citations
    }


def test_reporting_deadline_handles_sentence_separated_pronoun(temporal_pipeline) -> None:
    pre = temporal_pipeline.ask(
        "A change occurred on 15 February 2026. How many days did the recipient have to report it?"
    )
    post = temporal_pipeline.ask(
        "A change occurred on 15 March 2026. How many days did the recipient have to report it?"
    )

    assert pre.decision == Decision.CONFLICT
    assert "10 calendar days" in pre.answer
    assert "30 calendar days" in pre.answer
    assert post.decision == Decision.ANSWER
    assert "14-calendar-day" in post.answer
    assert "§None" not in pre.answer + post.answer


def test_missing_temporal_date_refuses_instead_of_guessing(temporal_pipeline) -> None:
    answer = temporal_pipeline.ask("How many days do I have to report a change?")

    assert answer.decision == Decision.REFUSE
    assert "date the change of circumstances occurred" in answer.answer
    assert answer.next_step


def test_claim_period_range_crossing_effective_date_uses_spanning_rule(temporal_pipeline) -> None:
    answer = temporal_pipeline.ask(
        "For a claim period from 20 February 2026 through 10 March 2026, "
        "how should the award be calculated?"
    )

    assert answer.decision == Decision.ANSWER
    assert "Use the figures in force on each day" in answer.answer
    assert {"7.4.3", None} <= {citation.clause_id for citation in answer.citations}
    assert "Amendment No. 2026-01 ¶5.3" in {
        citation.source_locator_label for citation in answer.citations
    }


def test_temporal_evaluation_set_uses_real_manual_and_amendment_locators(project_root) -> None:
    chunks = parse_policy_sources(
        project_root / "data" / "policy-manual.md",
        [project_root / "data" / "amendment-2026-01.md"],
    )
    questions = load_questions(project_root / "evaluation" / "temporal_questions.json")

    validate_question_clause_ids(
        questions,
        {chunk.clause_id for chunk in chunks if chunk.clause_id},
        {chunk.source_locator for chunk in chunks if chunk.source_locator},
    )
    assert len(questions) >= 10
    assert any(
        "amendment-2026-01:4.2" in question["expected_source_locators"]
        for question in questions
    )
