"""Composition root for the source-first policy evidence pipeline."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path

from config.settings import Settings
from src.artifact_integrity import resolve_local_directory, sha256_directory
from src.decision_engine import DecisionEngine
from src.embeddings import EmbeddingEngine
from src.evidence import EvidenceAnalyzer
from src.generator import AnswerBuilder
from src.models import (
    CombinedCorpusReport,
    Decision,
    EvidenceLevel,
    IngestionReport,
    PolicyAnswer,
    PolicyChunk,
)
from src.observability import PipelineTracer
from src.parser import (
    build_combined_corpus_report,
    build_corpus_report,
    find_chunks,
    parse_policy_manual,
    parse_policy_sources,
    persist_chunks,
)
from src.refusal import load_contacts, select_next_step
from src.retriever import Retriever
from src.temporal import TemporalPolicyResolver
from src.vector_store import IndexIntegrityError, VectorStore

LOGGER = logging.getLogger("grounded_answer")


def ingest_corpus(settings: Settings) -> tuple[IngestionReport | CombinedCorpusReport, dict]:
    """Parse, persist, embed, and index the configured source corpus."""

    paths = settings.source_paths
    if len(paths) == 1:
        chunks = parse_policy_manual(paths[0])
        report = build_corpus_report(paths[0], chunks)
    else:
        chunks = parse_policy_sources(paths[0], paths[1:])
        report = build_combined_corpus_report(paths, chunks)
        
    persist_chunks(chunks, report, settings.processed_path, settings.corpus_report_path)

    engine = EmbeddingEngine(
        settings.embedding_model,
        backend=settings.embedding_backend,
        dimension=settings.embedding_dimension,
    )
    embeddings = engine.encode_clauses(chunks)
    local_embedding = (
        resolve_local_directory(
            settings.embedding_model,
            base_dir=settings.project_root,
        )
        if engine.backend == "sentence-transformers"
        else None
    )
    embedding_artifact_sha256 = (
        sha256_directory(local_embedding) if local_embedding is not None else None
    )
    store = VectorStore(engine.dimension)
    store.build(
        embeddings,
        chunks,
        embedding_backend=engine.backend,
        embedding_model=engine.model_name,
        embedding_artifact_sha256=embedding_artifact_sha256,
        corpus_sha256=report.source_sha256,
    )
    store.save(settings.index_dir)
    return report, store.manifest


class GroundedAnswerPipeline:
    """Retrieve → assess → detect conflicts → decide → build → validate."""

    def __init__(
        self,
        settings: Settings,
        embedding_engine: EmbeddingEngine,
        store: VectorStore,
        *,
        llm_provider=None,
        tracer=None,
    ) -> None:
        self.settings = settings
        self.embedding_engine = embedding_engine
        self.store = store
        self._validate_policy_companions(settings, store.chunks)
        self.temporal_resolver = TemporalPolicyResolver(
            store.chunks,
            timeline_path=settings.timeline_path,
            contacts_path=settings.contacts_path,
        )
        self.retriever = Retriever(
            embedding_engine,
            store,
            use_hybrid=settings.enable_hybrid_search,
            use_reranker=settings.enable_reranking,
            require_reranker=settings.require_reranker,
            use_neighbors=settings.enable_neighbor_retrieval,
            initial_k=settings.initial_retrieval_k,
            rerank_k=settings.rerank_k,
            final_k=settings.final_k,
            rrf_k=settings.rrf_k,
            reranker_model=settings.reranker_model,
            findings_path=settings.findings_path,
        )
        self.evidence_analyzer = EvidenceAnalyzer(
            store.chunks,
            refusal_threshold=settings.refusal_threshold,
            direct_coverage_threshold=settings.direct_coverage_threshold,
            findings_path=settings.findings_path,
        )
        self.decision_engine = DecisionEngine(
            refusal_threshold=settings.refusal_threshold,
            findings_path=settings.findings_path,
            enable_conflict_check=settings.enable_contradiction_check,
        )
        self.answer_builder = AnswerBuilder(
            contacts_path=settings.contacts_path,
            findings_path=settings.findings_path,
            llm_provider=llm_provider,
            enable_claim_validation=settings.enable_claim_validation,
        )
        self.tracer = tracer or PipelineTracer(settings)

    @classmethod
    def load(cls, settings: Settings) -> GroundedAnswerPipeline:
        manifest_path = settings.index_dir / VectorStore.MANIFEST_NAME
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Policy index not found at {settings.index_dir}. Run `python main.py ingest` first."
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexIntegrityError("Index manifest is unreadable; rebuild the index") from exc

        backend = manifest.get("embedding_backend")
        model = manifest.get("embedding_model")
        dimension = int(manifest.get("dimension", -1))
        if backend != settings.embedding_backend:
            raise IndexIntegrityError(
                f"Configured embedding backend {settings.embedding_backend!r} does not match indexed "
                f"backend {backend!r}. Re-run ingest with the desired backend."
            )
        if backend == "sentence-transformers" and model != settings.embedding_model:
            raise IndexIntegrityError(
                f"Configured embedding model {settings.embedding_model!r} does not match index model {model!r}."
            )
        cls._validate_embedding_artifact(settings, manifest)

        engine = EmbeddingEngine(
            settings.embedding_model,
            backend=backend,
            dimension=dimension,
        )
        store = VectorStore(engine.dimension)
        store.load(settings.index_dir)
        cls._validate_corpus_identity(settings.source_paths, store.manifest)
        cls._validate_chunk_metadata(settings.source_paths, store.chunks)

        provider = None
        if settings.llm_provider == "gemini":
            from src.llm import GeminiProvider

            provider = GeminiProvider(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                thinking_level=settings.gemini_thinking_level,
            )
        return cls(settings, engine, store, llm_provider=provider)

    @staticmethod
    def _validate_embedding_artifact(settings: Settings, manifest: dict) -> None:
        """Verify a locally trained embedding directory against the index manifest."""

        if "embedding_artifact_sha256" not in manifest:
            return
        expected = manifest.get("embedding_artifact_sha256")
        if not isinstance(expected, str) or len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise IndexIntegrityError("Index manifest has an invalid embedding artifact digest")

        local_embedding = resolve_local_directory(
            settings.embedding_model,
            base_dir=settings.project_root,
        )
        if local_embedding is None:
            raise IndexIntegrityError(
                "The indexed embedding artifact was local, but the configured model directory is missing"
            )
        try:
            actual = sha256_directory(local_embedding)
        except (OSError, RuntimeError, ValueError) as exc:
            raise IndexIntegrityError(
                f"Could not verify the local embedding artifact: {local_embedding}"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise IndexIntegrityError(
                "The local embedding artifact differs from the model used to build the index; "
                "restore the artifact or re-run ingest"
            )

    @staticmethod
    def _validate_corpus_identity(source_paths: tuple[Path, ...], manifest: dict) -> None:
        from src.parser import source_bundle_sha256
        for path in source_paths:
            if not path.exists():
                raise FileNotFoundError(f"Configured policy corpus is missing: {path}")
        actual = source_bundle_sha256(source_paths)
        expected = manifest.get("corpus_sha256")
        if not expected or actual != expected:
            raise IndexIntegrityError(
                "The corpus differs from the indexed source. Run `python main.py ingest` before asking questions."
            )

    @staticmethod
    def _validate_chunk_metadata(source_paths: tuple[Path, ...], indexed: list[PolicyChunk]) -> None:
        """Ensure citation metadata is a faithful derivation of the source file."""
        from src.parser import parse_policy_manual, parse_policy_sources
        if len(source_paths) == 1:
            canonical = parse_policy_manual(source_paths[0])
        else:
            canonical = parse_policy_sources(source_paths[0], source_paths[1:])
            
        if len(canonical) != len(indexed):
            raise IndexIntegrityError(
                "Indexed citation metadata does not match the source corpus; run `python main.py ingest`."
            )
        for expected, actual in zip(canonical, indexed, strict=True):
            if expected.model_dump(mode="json") != actual.model_dump(mode="json"):
                raise IndexIntegrityError(
                    "Indexed citation metadata does not match the source corpus; run `python main.py ingest`."
                )

    @staticmethod
    def _validate_policy_companions(settings: Settings, chunks: list[PolicyChunk]) -> None:
        """Reject stale reviewed findings or escalation metadata after an update."""

        if not chunks:
            raise IndexIntegrityError("The policy index contains no trusted clauses")

        def read_object(path: Path, label: str) -> dict:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IndexIntegrityError(f"{label} metadata is unreadable: {path}") from exc
            if not isinstance(payload, dict):
                raise IndexIntegrityError(f"{label} metadata must contain a JSON object: {path}")
            return payload

        expected_document = chunks[0].document_id
        expected_date = chunks[0].effective_date
        known_clause_ids = {chunk.clause_id for chunk in chunks if chunk.clause_id}
        findings = read_object(settings.findings_path, "Policy findings")
        contacts = read_object(settings.contacts_path, "Escalation contacts")

        for label, payload in (("Policy findings", findings), ("Escalation contacts", contacts)):
            if payload.get("source_verified") is not True:
                raise IndexIntegrityError(f"{label} must be explicitly source verified")
            if payload.get("document_id") != expected_document:
                raise IndexIntegrityError(
                    f"{label} targets a different policy document; review it before serving answers"
                )
            if payload.get("consolidated_as_of") != expected_date:
                raise IndexIntegrityError(
                    f"{label} is stale for policy version {expected_date}; review it before serving answers"
                )

        referenced: set[str] = set()
        for group in ("conflicts", "gaps"):
            for item in findings.get(group, []):
                if not isinstance(item, dict) or item.get("source_verified") is not True:
                    raise IndexIntegrityError(f"Every reviewed {group} item must be source verified")
                referenced.update(str(value) for value in item.get("clause_ids", []))
                referenced.update(str(value) for value in item.get("context_clause_ids", []))
        for key in ("default", "eligibility", "appeals", "conflict"):
            item = contacts.get(key)
            if not isinstance(item, dict) or not str(item.get("next_step", "")).strip():
                raise IndexIntegrityError(f"Escalation contacts is missing a valid {key!r} route")
            referenced.update(str(value) for value in item.get("source_clause_ids", []))

        unknown = sorted(referenced - known_clause_ids)
        if unknown:
            raise IndexIntegrityError(
                "Reviewed policy metadata cites unknown clauses: " + ", ".join(unknown)
            )

    def ask(self, question: str, *, include_trace: bool = False) -> PolicyAnswer:
        normalized = question.strip()
        if not normalized:
            raise ValueError("Question must not be empty")
        model = self.settings.gemini_model if self.settings.llm_provider == "gemini" else "deterministic"
        with self.tracer.query(
            normalized,
            include_debug_trace=include_trace,
            embedding_backend=self.settings.embedding_backend,
            answer_provider=self.settings.llm_provider,
            model=model,
        ) as query_span:
            with self.tracer.span("temporal-applicability", "tool") as temporal_span:
                temporal_answer = self.temporal_resolver.resolve(normalized, include_trace=include_trace)
                if temporal_answer is not None:
                    temporal_span.end({"decision": temporal_answer.decision.value})
                    query_span.end(
                        {
                            "decision": temporal_answer.decision.value,
                            "evidence_level": temporal_answer.evidence_level.value,
                            "citation_count": len(temporal_answer.citations),
                            "citation_clause_ids": [
                                citation.clause_id or citation.chunk_id for citation in temporal_answer.citations
                            ],
                            "citation_validation": "valid",
                        }
                    )
                    return temporal_answer
                temporal_span.end({"decision": "skipped"})

            with self.tracer.span("retrieve-policy-evidence", "retriever") as retrieval_span:
                retrieved = self.retriever.retrieve(normalized)
                retrieval_span.end(
                    {
                        "result_count": len(retrieved),
                        "clause_ids": [
                            item.chunk.clause_id or item.chunk.chunk_id for item in retrieved
                        ],
                    }
                )

            with self.tracer.span("assess-evidence", "tool") as evidence_span:
                evidence = self.evidence_analyzer.assess(normalized, retrieved)
                support_counts: dict[str, int] = {}
                for assessment in evidence:
                    key = assessment.support_type.value
                    support_counts[key] = support_counts.get(key, 0) + 1
                evidence_span.end({"support_counts": support_counts})

            with self.tracer.span("decide-answer-state", "chain") as decision_span:
                trace = self.decision_engine.decide(normalized, retrieved, evidence)
                decision_span.end(
                    {
                        "decision": trace.decision.value,
                        "conflict_count": len(trace.conflicts),
                    }
                )

            generation_error: Exception | None = None
            run_type = "llm" if self.settings.llm_provider == "gemini" else "chain"
            with self.tracer.span(
                "build-validated-answer",
                run_type,
                {
                    "answer_provider": self.settings.llm_provider,
                    "model": model,
                },
            ) as generation_span:
                try:
                    answer = self.answer_builder.build(trace, include_trace=include_trace)
                    citation_status = "valid"
                    generation_span.end(
                        {
                            "status": "valid",
                            "decision": answer.decision.value,
                            "evidence_level": answer.evidence_level.value,
                            "citation_count": len(answer.citations),
                            "citation_clause_ids": [
                                citation.clause_id or citation.chunk_id
                                for citation in answer.citations
                            ],
                        }
                    )
                except Exception as exc:
                    generation_error = exc
                    citation_status = "rejected"
                    generation_span.end(
                        {
                            "status": "rejected",
                            "error_type": type(exc).__name__,
                            "citation_validation": citation_status,
                        }
                    )

            if generation_error is not None:
                # Generation/provider/citation failures can never fall through to an
                # unvalidated answer. Convert them into an explicit safe refusal.
                safe_trace = trace.model_copy(
                    update={
                        "decision": Decision.REFUSE,
                        "decision_reason": (
                            "A generated answer failed the citation or provider safety check "
                            f"({type(generation_error).__name__}); no policy answer was shown."
                        ),
                    }
                )
                contacts = load_contacts(self.settings.contacts_path)
                answer = PolicyAnswer(
                    decision=Decision.REFUSE,
                    answer=(
                        "I don't know based on the current policy manual. "
                        "A safe, citation-validated answer could not be produced."
                    ),
                    evidence_level=EvidenceLevel.LOW,
                    reason=safe_trace.decision_reason,
                    next_step=select_next_step(normalized, contacts),
                    trace=safe_trace if include_trace else None,
                )

            LOGGER.info(
                "query=%r retrieved=%s decision=%s reason=%r citation_validation=%s",
                normalized,
                [item.chunk.chunk_id for item in retrieved],
                answer.decision.value,
                answer.reason,
                citation_status,
            )
            query_span.end(
                {
                    "decision": answer.decision.value,
                    "evidence_level": answer.evidence_level.value,
                    "citation_count": len(answer.citations),
                    "citation_clause_ids": [
                        citation.clause_id or citation.chunk_id for citation in answer.citations
                    ],
                    "citation_validation": citation_status,
                }
            )
            return answer

    def flush_traces(self, timeout: float = 10.0) -> None:
        """Flush pending optional observability writes."""

        self.tracer.flush(timeout=timeout)

    def source(self, source_id: str) -> list[PolicyChunk]:
        return find_chunks(self.store.chunks, source_id)


def load_source_chunks(settings: Settings) -> list[PolicyChunk]:
    """Read source lookup metadata directly from the authoritative corpus."""

    paths = settings.source_paths
    if len(paths) == 1:
        return parse_policy_manual(paths[0])
    return parse_policy_sources(paths[0], paths[1:])
