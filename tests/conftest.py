from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

import pytest

from config.settings import Settings
from src.embeddings import EmbeddingEngine
from src.models import PolicyChunk, RetrievedClause
from src.parser import parse_policy_manual
from src.pipeline import GroundedAnswerPipeline
from src.vector_store import VectorStore


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def corpus_path(project_root: Path) -> Path:
    return project_root / "data" / "policy-manual.md"


@pytest.fixture(scope="session")
def findings_path(project_root: Path) -> Path:
    return project_root / "data" / "policy_findings.json"


@pytest.fixture(scope="session")
def contacts_path(project_root: Path) -> Path:
    return project_root / "data" / "contacts.json"


@pytest.fixture(scope="session")
def chunks(corpus_path: Path) -> list[PolicyChunk]:
    return parse_policy_manual(corpus_path)


@pytest.fixture(scope="session")
def hashing_engine() -> EmbeddingEngine:
    return EmbeddingEngine(backend="hashing", dimension=256)


@pytest.fixture(scope="session")
def vector_store(
    chunks: list[PolicyChunk],
    hashing_engine: EmbeddingEngine,
    corpus_path: Path,
) -> VectorStore:
    store = VectorStore(hashing_engine.dimension)
    store.build(
        hashing_engine.encode_clauses(chunks),
        chunks,
        embedding_backend=hashing_engine.backend,
        embedding_model=hashing_engine.model_name,
        corpus_sha256=hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
    )
    return store


@pytest.fixture(scope="session")
def pipeline_settings(
    tmp_path_factory: pytest.TempPathFactory,
    project_root: Path,
    corpus_path: Path,
    findings_path: Path,
    contacts_path: Path,
) -> Settings:
    runtime = tmp_path_factory.mktemp("pipeline-runtime")
    return Settings(
        project_root=project_root,
        corpus_path=corpus_path,
        processed_path=runtime / "chunks.json",
        corpus_report_path=runtime / "corpus-report.json",
        index_dir=runtime / "indexes",
        findings_path=findings_path,
        contacts_path=contacts_path,
        embedding_backend="hashing",
        embedding_dimension=256,
        enable_hybrid_search=True,
        enable_reranking=False,
        enable_neighbor_retrieval=True,
        llm_provider="deterministic",
    )


@pytest.fixture(scope="session")
def pipeline(
    pipeline_settings: Settings,
    hashing_engine: EmbeddingEngine,
    vector_store: VectorStore,
) -> GroundedAnswerPipeline:
    return GroundedAnswerPipeline(pipeline_settings, hashing_engine, vector_store)


@pytest.fixture
def make_chunk() -> Callable[..., PolicyChunk]:
    def factory(
        *,
        chunk_id: str = "chunk_test_001",
        clause_id: str = "1.1.1",
        text: str = "A test policy rule.",
        section_id: str = "1.1",
        section_title: str = "Test rules",
        source_order: int = 0,
        cross_references: list[str] | None = None,
    ) -> PolicyChunk:
        source_text = f"**{clause_id}** {text}"
        return PolicyChunk(
            chunk_id=chunk_id,
            document_id="test-policy",
            document_name="test-policy.md",
            document_version="test-v1",
            effective_date="2025-01-01",
            text=text,
            raw_text=text,
            normalized_text=" ".join(text.lower().split()),
            source_text=source_text,
            part_id="1",
            part_title="Test",
            section_id=section_id,
            section_title=section_title,
            clause_id=clause_id,
            page=None,
            line_start=1,
            line_end=1,
            start_offset=0,
            end_offset=len(source_text.encode("utf-8")),
            source_order=source_order,
            cross_references=cross_references or [],
        )

    return factory


@pytest.fixture
def make_result() -> Callable[..., RetrievedClause]:
    def factory(
        chunk: PolicyChunk,
        *,
        vector_score: float | None = 0.7,
        lexical_score: float | None = 0.8,
        fused_score: float | None = 0.8,
    ) -> RetrievedClause:
        return RetrievedClause(
            chunk=chunk,
            vector_score=vector_score,
            lexical_score=lexical_score,
            fused_score=fused_score,
        )

    return factory
