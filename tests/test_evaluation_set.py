import pytest
from src.pipeline import GroundedAnswerPipeline
from src.models import Decision

from src.parser import parse_policy_sources, source_bundle_sha256
from src.embeddings import EmbeddingEngine
from src.vector_store import VectorStore
from config.settings import Settings

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

def test_earnings_disregard_amended(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("What is the earnings disregard for a claim date April 2026?")
    assert answer.decision == Decision.ANSWER
    assert "$175" in answer.answer
    assert "6.4.1" in [c.clause_id for c in answer.citations]

def test_household_resource_limit(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("What is the household resource limit?")
    assert answer.decision == Decision.ANSWER
    assert "$4,000" in answer.answer
    assert "2.4.1" in [c.clause_id for c in answer.citations]

def test_reporting_period_before_amendment(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("How many days do I have to report a change that happened on 15 February 2026?")
    assert answer.decision == Decision.ANSWER
    assert "10" in answer.answer
    assert "30" not in answer.answer

def test_reporting_period_after_amendment(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("How many days do I have to report a change that happened on 15 March 2026?")
    assert answer.decision == Decision.ANSWER
    assert "14" in answer.answer

def test_appeal_time_limit(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("An appeal must be lodged within 21 days of the date on the notice of the review decision.")
    assert answer.decision == Decision.ANSWER
    assert any(c.clause_id in ["12.1.2", "12.1.4"] for c in answer.citations)

def test_no_fixed_address(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("How is connection established for an applicant with no fixed address?")
    assert answer.decision == Decision.ANSWER
    assert "3.3.1" in [c.clause_id for c in answer.citations]

def test_motor_vehicle_resource(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("Does my car count towards the resource limit?")
    assert answer.decision == Decision.ANSWER
    assert "2.4.2" in [c.clause_id for c in answer.citations]

def test_appeal_without_review(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("Can an appeal be lodged before a review has been completed?")
    assert answer.decision == Decision.ANSWER
    assert "12.1.3" in [c.clause_id for c in answer.citations]

def test_17_year_old_applicant(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("Is a person aged 16 or 17 eligible for assistance?")
    assert answer.decision == Decision.ANSWER
    assert "2.3.1" in [c.clause_id for c in answer.citations]

def test_unrelated_question(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("What color is the sky according to the manual?")
    assert answer.decision == Decision.REFUSE

def test_dependent_child_adjustment(temporal_pipeline: GroundedAnswerPipeline):
    answer = temporal_pipeline.ask("The needs figure is increased by $140 per month where the household includes a dependent child under the age of 2.")
    assert answer.decision == Decision.ANSWER
    assert "7.3.2" in [c.clause_id for c in answer.citations]
