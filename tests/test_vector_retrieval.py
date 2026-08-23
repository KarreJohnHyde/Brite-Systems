from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from src.embeddings import EmbeddingEngine
from src.lexical import BM25Index
from src.pipeline import GroundedAnswerPipeline
from src.retriever import RerankerUnavailableError, Retriever
from src.vector_store import IndexIntegrityError, VectorStore


def test_hashing_embeddings_are_normalized_and_deterministic(chunks) -> None:
    first = EmbeddingEngine(backend="hashing", dimension=128)
    second = EmbeddingEngine(backend="hashing", dimension=128)

    vectors_a = first.encode_clauses(chunks[:3])
    vectors_b = second.encode_clauses(chunks[:3])

    assert vectors_a.shape == (3, 128)
    assert vectors_a.dtype == np.float32
    np.testing.assert_array_equal(vectors_a, vectors_b)
    np.testing.assert_allclose(np.linalg.norm(vectors_a, axis=1), np.ones(3), atol=1e-6)


def test_vector_index_persists_and_reloads_identical_searches(
    tmp_path: Path,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    query = hashing_engine.encode_query("household resource limit")
    before = vector_store.search(query, k=8)
    vector_store.save(tmp_path)

    loaded = VectorStore(hashing_engine.dimension)
    loaded.load(tmp_path)
    after = loaded.search(query, k=8)

    assert [chunk.chunk_id for chunk, _ in after] == [chunk.chunk_id for chunk, _ in before]
    np.testing.assert_allclose(
        [score for _, score in after],
        [score for _, score in before],
        atol=1e-7,
    )
    assert loaded.manifest == vector_store.manifest


def test_vector_manifest_records_local_embedding_artifact_digest(
    chunks,
    hashing_engine: EmbeddingEngine,
) -> None:
    digest = "a" * 64
    store = VectorStore(hashing_engine.dimension)
    store.build(
        hashing_engine.encode_clauses(chunks[:2]),
        chunks[:2],
        embedding_backend="sentence-transformers",
        embedding_model="models/candidate",
        embedding_artifact_sha256=digest,
    )

    assert store.manifest["embedding_artifact_sha256"] == digest


def test_vector_manifest_rejects_invalid_embedding_artifact_digest(
    chunks,
    hashing_engine: EmbeddingEngine,
) -> None:
    store = VectorStore(hashing_engine.dimension)

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        store.build(
            hashing_engine.encode_clauses(chunks[:2]),
            chunks[:2],
            embedding_artifact_sha256="not-a-digest",
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("schema_version", 1, "Unsupported index schema"),
        ("dimension", 999, "dimension mismatch"),
        ("chunks", 149, "count mismatch"),
    ],
)
def test_index_manifest_integrity_mismatches_are_rejected(
    tmp_path: Path,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
    field: str,
    replacement: int,
    message: str,
) -> None:
    vector_store.save(tmp_path)
    manifest_path = tmp_path / VectorStore.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = replacement
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IndexIntegrityError, match=message):
        VectorStore(hashing_engine.dimension).load(tmp_path)


def test_index_metadata_count_mismatch_is_rejected(
    tmp_path: Path,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    vector_store.save(tmp_path)
    metadata_path = tmp_path / VectorStore.METADATA_NAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_path.write_text(json.dumps(metadata[:-1]), encoding="utf-8")

    with pytest.raises(IndexIntegrityError, match="count mismatch"):
        VectorStore(hashing_engine.dimension).load(tmp_path)


def test_duplicate_trusted_chunk_ids_in_metadata_are_rejected(
    tmp_path: Path,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    vector_store.save(tmp_path)
    metadata_path = tmp_path / VectorStore.METADATA_NAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata[1]["chunk_id"] = metadata[0]["chunk_id"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(IndexIntegrityError, match="Duplicate trusted chunk IDs"):
        VectorStore(hashing_engine.dimension).load(tmp_path)


def test_metadata_checksum_rejects_same_shape_text_tampering(
    tmp_path: Path,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    vector_store.save(tmp_path)
    metadata_path = tmp_path / VectorStore.METADATA_NAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata[0]["text"] = "Tampered policy text with the same record count."
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(IndexIntegrityError, match="metadata checksum mismatch"):
        VectorStore(hashing_engine.dimension).load(tmp_path)


def test_index_checksum_in_manifest_is_enforced(
    tmp_path: Path,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    vector_store.save(tmp_path)
    manifest_path = tmp_path / VectorStore.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["index_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IndexIntegrityError, match="FAISS index checksum mismatch"):
        VectorStore(hashing_engine.dimension).load(tmp_path)


def test_query_dimension_mismatch_is_rejected(vector_store: VectorStore) -> None:
    with pytest.raises(ValueError, match="Query embedding shape"):
        vector_store.search(np.zeros((1, 8), dtype="float32"))


def test_hybrid_retrieval_finds_exact_numeric_policy_clause(
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
    findings_path: Path,
) -> None:
    retriever = Retriever(
        hashing_engine,
        vector_store,
        use_hybrid=True,
        use_reranker=False,
        use_neighbors=False,
        findings_path=findings_path,
    )

    results = retriever.retrieve("What is the household resource limit?")
    matching = next(item for item in results if item.chunk.clause_id == "2.4.1")

    assert results[0].chunk.clause_id == "2.4.1"
    assert matching.vector_score is not None
    assert matching.lexical_score is not None
    assert matching.fused_score is not None


def test_bm25_preserves_exact_technical_term_recall(chunks) -> None:
    results = BM25Index(chunks).search("beneficial interest in jointly held resources", k=5)

    assert results
    assert results[0][0].clause_id == "2.4.3"
    assert results[0][1] == pytest.approx(1.0)


def test_bm25_conservatively_recovers_common_policy_typos(chunks) -> None:
    results = BM25Index(chunks).search(
        "whats the max resorce amount a houshold can hav?",
        k=5,
    )

    assert results
    assert results[0][0].clause_id == "2.4.1"


def test_reranker_cannot_discard_the_top_lexical_anchor(
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    class AdversarialReranker:
        @staticmethod
        def predict(pairs):
            return np.array(
                [-20.0 if "$4,000" in passage else 20.0 for _, passage in pairs]
            )

    retriever = Retriever(
        hashing_engine,
        vector_store,
        use_hybrid=True,
        use_reranker=False,
        use_neighbors=False,
        final_k=6,
    )
    retriever.reranker = AdversarialReranker()

    results = retriever.retrieve("whats the max resorce amount a houshold can hav?")

    assert "2.4.1" in {item.chunk.clause_id for item in results}


def test_required_reranker_fails_closed_when_model_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    fake_module = types.ModuleType("sentence_transformers")

    class BrokenCrossEncoder:
        def __init__(self, model_name: str) -> None:
            raise OSError(f"missing model: {model_name}")

    fake_module.CrossEncoder = BrokenCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    with pytest.raises(RerankerUnavailableError, match="could not be loaded"):
        Retriever(
            hashing_engine,
            vector_store,
            use_reranker=True,
            require_reranker=True,
            use_neighbors=False,
        )


def test_required_reranker_fails_closed_when_prediction_fails(
    monkeypatch: pytest.MonkeyPatch,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    fake_module = types.ModuleType("sentence_transformers")

    class BrokenCrossEncoder:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        @staticmethod
        def predict(pairs):
            raise RuntimeError("prediction failed")

    fake_module.CrossEncoder = BrokenCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    retriever = Retriever(
        hashing_engine,
        vector_store,
        use_reranker=True,
        require_reranker=True,
        use_neighbors=False,
    )

    with pytest.raises(RerankerUnavailableError, match="failed during prediction"):
        retriever.retrieve("What is the household resource limit?")


def test_optional_reranker_prediction_failure_preserves_baseline_candidates(
    monkeypatch: pytest.MonkeyPatch,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    fake_module = types.ModuleType("sentence_transformers")

    class BrokenCrossEncoder:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        @staticmethod
        def predict(pairs):
            raise RuntimeError("prediction failed")

    fake_module.CrossEncoder = BrokenCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    retriever = Retriever(
        hashing_engine,
        vector_store,
        use_reranker=True,
        require_reranker=False,
        use_neighbors=False,
    )

    results = retriever.retrieve("What is the household resource limit?")

    assert results
    assert retriever.reranker_error == "prediction failed"


def test_neighbor_expansion_keeps_standard_and_extended_absence_rules(
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
    findings_path: Path,
) -> None:
    retriever = Retriever(
        hashing_engine,
        vector_store,
        use_hybrid=True,
        use_neighbors=True,
        use_reranker=False,
        findings_path=findings_path,
    )

    results = retriever.retrieve(
        "How long may a recipient be temporarily absent, including exceptions?"
    )
    clause_ids = {item.chunk.clause_id for item in results}

    assert {"3.2.1", "3.2.2", "3.2.4"} <= clause_ids


def test_hashing_hybrid_retrieval_performs_no_network_calls(
    monkeypatch: pytest.MonkeyPatch,
    vector_store: VectorStore,
    hashing_engine: EmbeddingEngine,
) -> None:
    import socket

    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", blocked)
    retriever = Retriever(
        hashing_engine,
        vector_store,
        use_hybrid=True,
        use_reranker=False,
        use_neighbors=False,
    )

    assert retriever.retrieve("What is the appeal deadline?")


def test_corpus_hash_mismatch_is_rejected(tmp_path: Path, corpus_path: Path) -> None:
    altered = tmp_path / "policy-manual.md"
    altered.write_bytes(corpus_path.read_bytes() + b"\n<!-- changed -->\n")
    manifest = {"corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest()}

    with pytest.raises(IndexIntegrityError, match="corpus differs"):
        GroundedAnswerPipeline._validate_corpus_identity((altered,), manifest)


def test_indexed_citation_metadata_must_match_authoritative_source(
    corpus_path: Path,
    chunks,
) -> None:
    tampered = list(chunks)
    tampered[0] = tampered[0].model_copy(update={"line_start": 999})

    with pytest.raises(IndexIntegrityError, match="citation metadata does not match"):
        GroundedAnswerPipeline._validate_chunk_metadata((corpus_path,), tampered)


def test_stale_reviewed_findings_are_rejected_after_policy_update(
    tmp_path: Path,
    pipeline_settings,
    chunks,
    findings_path: Path,
) -> None:
    stale_path = tmp_path / "stale-findings.json"
    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    payload["consolidated_as_of"] = "2025-09-30"
    stale_path.write_text(json.dumps(payload), encoding="utf-8")
    settings = pipeline_settings.model_copy(update={"findings_path": stale_path})

    with pytest.raises(IndexIntegrityError, match="stale for policy version"):
        GroundedAnswerPipeline._validate_policy_companions(settings, chunks)


def test_unknown_contact_source_clause_is_rejected(
    tmp_path: Path,
    pipeline_settings,
    chunks,
    contacts_path: Path,
) -> None:
    contacts_copy = tmp_path / "contacts.json"
    payload = json.loads(contacts_path.read_text(encoding="utf-8"))
    payload["default"]["source_clause_ids"].append("99.9.9")
    contacts_copy.write_text(json.dumps(payload), encoding="utf-8")
    settings = pipeline_settings.model_copy(update={"contacts_path": contacts_copy})

    with pytest.raises(IndexIntegrityError, match="unknown clauses"):
        GroundedAnswerPipeline._validate_policy_companions(settings, chunks)
