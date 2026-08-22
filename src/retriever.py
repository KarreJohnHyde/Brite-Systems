"""Hybrid retrieval, fusion, optional reranking, and evidence-context expansion."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from src.embeddings import EmbeddingEngine
from src.lexical import BM25Index, tokenize
from src.models import PolicyChunk, RetrievedClause
from src.vector_store import VectorStore


NUMERIC_QUESTION_RE = re.compile(
    r"\b(how (?:many|much|long)|time limit|deadline|amount|rate|percentage|threshold|limit)\b",
    re.I,
)
NUMERIC_PASSAGE_RE = re.compile(
    r"(?:\$\s*\d|\b\d+(?:\.\d+)?\s*(?:calendar\s+|working\s+)?(?:days?|weeks?|months?|years?|per\s*cent|percent|%))",
    re.I,
)
LIST_QUESTION_RE = re.compile(
    r"\b(which|what (?:are|is|income|resources?|conditions?|evidence|ways?|documents?|types?|kinds?))\b",
    re.I,
)
CLAUSE_ID_RE = re.compile(r"§?(\d+\.\d+(?:\.\d+)?)")


class Retriever:
    """Combine dense and BM25 retrieval while preserving independent scores."""

    def __init__(
        self,
        embedding_engine: EmbeddingEngine,
        vector_store: VectorStore,
        *,
        use_hybrid: bool = True,
        use_reranker: bool = False,
        use_neighbors: bool = True,
        initial_k: int = 18,
        rerank_k: int = 8,
        final_k: int = 6,
        rrf_k: int = 60,
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        findings_path: str | Path | None = None,
    ) -> None:
        self.embedding_engine = embedding_engine
        self.vector_store = vector_store
        self.use_hybrid = use_hybrid
        self.use_reranker = use_reranker
        self.use_neighbors = use_neighbors
        self.initial_k = initial_k
        self.rerank_k = rerank_k
        self.final_k = final_k
        self.rrf_k = rrf_k
        self.reranker_model = reranker_model
        self.lexical = BM25Index(vector_store.chunks)
        self.reranker: Any | None = None
        self.reranker_error: str | None = None
        self.findings = self._load_findings(findings_path)
        self._by_clause = {chunk.clause_id: chunk for chunk in vector_store.chunks if chunk.clause_id}
        self._by_section: dict[str, list[PolicyChunk]] = {}
        for chunk in vector_store.chunks:
            if chunk.section_id:
                self._by_section.setdefault(chunk.section_id, []).append(chunk)
        if use_reranker:
            self._load_reranker()

    def _load_reranker(self) -> None:
        try:
            from sentence_transformers import CrossEncoder

            self.reranker = CrossEncoder(self.reranker_model)
        except Exception as exc:
            self.reranker_error = str(exc)
            self.reranker = None

    @staticmethod
    def _load_findings(path: str | Path | None) -> dict[str, Any]:
        if not path:
            return {"conflicts": [], "gaps": []}
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(f"Policy findings file is missing: {source}")
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Policy findings file is unreadable: {source}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Policy findings file must contain a JSON object: {source}")
        if not isinstance(payload.get("conflicts", []), list) or not isinstance(payload.get("gaps", []), list):
            raise ValueError(f"Policy findings conflicts/gaps must be lists: {source}")
        return payload

    def retrieve(self, question: str) -> list[RetrievedClause]:
        """Retrieve a broad evidence set; no answer decision is made here."""

        if not question.strip():
            raise ValueError("Question must not be empty")
        vector_raw = self.vector_store.search(
            self.embedding_engine.encode_query(question), k=self.initial_k
        )
        lexical_raw = self.lexical.search(question, k=self.initial_k) if self.use_hybrid else []

        candidates: dict[str, RetrievedClause] = {}
        vector_scores = self._normalize_vector_scores([score for _, score in vector_raw])
        for rank, ((chunk, _), score) in enumerate(zip(vector_raw, vector_scores), start=1):
            candidates[chunk.chunk_id] = RetrievedClause(
                chunk=chunk,
                vector_score=score,
                vector_rank=rank,
            )
        for rank, (chunk, score) in enumerate(lexical_raw, start=1):
            existing = candidates.get(chunk.chunk_id)
            if existing:
                candidates[chunk.chunk_id] = existing.model_copy(
                    update={"lexical_score": score, "lexical_rank": rank}
                )
            else:
                candidates[chunk.chunk_id] = RetrievedClause(
                    chunk=chunk,
                    lexical_score=score,
                    lexical_rank=rank,
                )

        fused = [self._with_fused_score(result, question) for result in candidates.values()]
        fused.sort(key=lambda result: result.fused_score or 0.0, reverse=True)

        if self.reranker is not None and fused:
            fused = self._rerank(question, fused[: self.rerank_k]) + fused[self.rerank_k :]
            fused.sort(key=lambda result: result.ranking_score, reverse=True)

        primary = fused[: self.final_k]
        fused_candidates = {item.chunk.chunk_id: item for item in fused}
        expanded = self._expand_context(question, primary, fused_candidates) if self.use_neighbors else primary
        return expanded

    @staticmethod
    def _normalize_vector_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []
        # Cosine similarity is not evidence confidence. This is only a bounded
        # retrieval feature used for fusion.  Do not shift or max-normalize the
        # candidate set: doing so makes a collection of unrelated, near-zero
        # cosine scores appear highly relevant merely because one is the least
        # bad result.
        return [max(0.0, min(1.0, score)) for score in scores]

    def _with_fused_score(self, result: RetrievedClause, question: str) -> RetrievedClause:
        rrf = 0.0
        sources = 0
        if result.vector_rank is not None:
            rrf += 1.0 / (self.rrf_k + result.vector_rank)
            sources += 1
        if result.lexical_rank is not None:
            rrf += 1.0 / (self.rrf_k + result.lexical_rank)
            sources += 1
        # Hash features provide recall, while BM25 is substantially more precise
        # for this numbered policy corpus. MiniLM receives a larger dense weight.
        normalized_rrf = rrf / (2.0 / (self.rrf_k + 1)) if rrf else 0.0
        if self.embedding_engine.backend == "hashing":
            lexical_weight, vector_weight, agreement_weight = 0.84, 0.10, 0.06
        else:
            lexical_weight, vector_weight, agreement_weight = 0.56, 0.34, 0.10
        fused = (
            lexical_weight * (result.lexical_score or 0.0)
            + vector_weight * (result.vector_score or 0.0)
            + agreement_weight * normalized_rrf
        )
        fused = min(1.0, fused + self._intent_boost(question, result.chunk))
        return result.model_copy(update={"fused_score": fused})

    @staticmethod
    def _intent_boost(question: str, chunk: PolicyChunk) -> float:
        boost = 0.0
        exact_refs = {match.group(1) for match in CLAUSE_ID_RE.finditer(question)}
        if chunk.clause_id in exact_refs or chunk.section_id in exact_refs:
            boost += 0.35
        if NUMERIC_QUESTION_RE.search(question) and NUMERIC_PASSAGE_RE.search(chunk.text):
            boost += 0.08
        if LIST_QUESTION_RE.search(question) and ("(a)" in chunk.text or "|" in chunk.raw_text):
            boost += 0.06
        question_terms = set(tokenize(question, expand=True))
        section_terms = set(tokenize(chunk.section_title or "", expand=False))
        if question_terms and section_terms:
            boost += min(0.16, 0.08 * len(question_terms & section_terms))
        if "appeal" in question_terms and (chunk.section_title or "").lower() == "right of appeal":
            boost += 0.18
        return boost

    def _rerank(self, question: str, candidates: list[RetrievedClause]) -> list[RetrievedClause]:
        pairs = [
            (question, f"{result.chunk.section_title}. {result.chunk.text}")
            for result in candidates
        ]
        try:
            raw_scores = self.reranker.predict(pairs)
        except Exception as exc:
            self.reranker_error = str(exc)
            return candidates

        reranked: list[RetrievedClause] = []
        ordered = sorted(enumerate(raw_scores), key=lambda item: float(item[1]), reverse=True)
        rank_by_index = {index: rank for rank, (index, _) in enumerate(ordered, start=1)}
        for index, (result, raw_score) in enumerate(zip(candidates, raw_scores)):
            probability_like = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(raw_score)))))
            combined = 0.65 * probability_like + 0.35 * (result.fused_score or 0.0)
            reranked.append(
                result.model_copy(
                    update={"reranker_score": combined, "reranker_rank": rank_by_index[index]}
                )
            )
        return reranked

    def _expand_context(
        self,
        question: str,
        primary: list[RetrievedClause],
        all_candidates: dict[str, RetrievedClause],
    ) -> list[RetrievedClause]:
        selected: dict[str, RetrievedClause] = {item.chunk.chunk_id: item for item in primary}

        def add(chunk: PolicyChunk, parent: RetrievedClause, reason: str) -> None:
            if chunk.chunk_id in selected:
                existing_selected = selected[chunk.chunk_id]
                inherited = max(existing_selected.ranking_score, parent.ranking_score * 0.92)
                selected[chunk.chunk_id] = existing_selected.model_copy(
                    update={
                        "fused_score": inherited,
                        "reranker_score": None,
                        "neighbor_of": reason if reason.startswith(("finding:", "intent:")) else existing_selected.neighbor_of,
                    }
                )
                return
            existing = all_candidates.get(chunk.chunk_id)
            if existing:
                inherited = max(existing.ranking_score, parent.ranking_score * 0.92)
                selected[chunk.chunk_id] = existing.model_copy(
                    update={"fused_score": inherited, "reranker_score": None, "neighbor_of": reason}
                )
                return
            inherited = max(0.0, min(1.0, parent.ranking_score * 0.92))
            selected[chunk.chunk_id] = RetrievedClause(
                chunk=chunk,
                fused_score=inherited,
                neighbor_of=reason,
            )

        ordered_chunks = self.vector_store.chunks
        for parent in primary[:4]:
            chunk = parent.chunk
            # Immediate siblings commonly contain conditions, exceptions, or effects.
            for offset in (-1, 1):
                index = chunk.source_order + offset
                if 0 <= index < len(ordered_chunks):
                    neighbor = ordered_chunks[index]
                    if neighbor.section_id == chunk.section_id:
                        add(neighbor, parent, chunk.chunk_id)
            # Resolve both clause- and section-level cross-references.
            for reference in chunk.cross_references:
                if reference in self._by_clause:
                    add(self._by_clause[reference], parent, chunk.chunk_id)
                for referenced in self._by_section.get(reference, []):
                    add(referenced, parent, chunk.chunk_id)
            if "exception" in question.lower() and chunk.section_id:
                for sibling in self._by_section.get(chunk.section_id, []):
                    add(sibling, parent, f"exception:{chunk.chunk_id}")

        if re.search(r"\b(am i|will i|exactly how much)\b", question, re.I) and primary:
            intent_titles = {
                "the basic conditions",
                "resources",
                "disregards",
                "income thresholds",
                "the award",
                "needs figures",
            }
            for section_chunks in self._by_section.values():
                if not section_chunks or (section_chunks[0].section_title or "").lower() not in intent_titles:
                    continue
                # Prefer the section's operative/list clause rather than every sibling.
                operative = max(
                    section_chunks,
                    key=lambda candidate: (
                        int(
                            "following" in candidate.text.lower()
                            or "threshold" in candidate.text.lower()
                            or "figure" in candidate.text.lower()
                            or "conditions are" in candidate.text.lower()
                        ),
                        -candidate.source_order,
                    ),
                )
                add(operative, primary[0], f"intent:{section_chunks[0].section_id}")

        # Human-reviewed corpus findings are retrieval metadata, not invented
        # policy. If a finding clearly matches the question and one side was
        # found, pin every cited side into the evidence pool.
        question_terms = set(tokenize(question, expand=True))
        for finding in self.findings.get("conflicts", []) + self.findings.get("gaps", []):
            topic_terms = {token for term in finding.get("topic_terms", []) for token in tokenize(term, expand=True)}
            overlap = question_terms & topic_terms
            primary_clause_ids = set(finding.get("clause_ids", []))
            clause_ids = primary_clause_ids | set(finding.get("context_clause_ids", []))
            has_seed = any(item.chunk.clause_id in clause_ids for item in selected.values())
            required_overlap = 1 if len(topic_terms) <= 2 else (2 if len(topic_terms) <= 5 else 3)
            patterns = finding.get("trigger_patterns", [])
            pattern_match = any(re.search(pattern, question, re.I) for pattern in patterns)
            if has_seed and (pattern_match or len(overlap) >= required_overlap):
                parent = next(item for item in selected.values() if item.chunk.clause_id in clause_ids)
                for clause_id in clause_ids:
                    chunk = self._by_clause.get(clause_id)
                    if chunk:
                        add(chunk, parent, f"finding:{finding.get('id', 'reviewed')}")

        # Keep a compact context and always retain source-verified finding sides.
        ranked = sorted(
            selected.values(),
            key=lambda result: (result.ranking_score, -result.chunk.source_order),
            reverse=True,
        )
        limit = self.final_k + 6
        compact = ranked[:limit]
        pinned = [
            item
            for item in ranked[limit:]
            if item.neighbor_of and item.neighbor_of.startswith(("finding:", "intent:"))
        ]
        for item in pinned:
            replaceable = next(
                (
                    index
                    for index in range(len(compact) - 1, -1, -1)
                    if not (compact[index].neighbor_of or "").startswith(("finding:", "intent:"))
                ),
                None,
            )
            if replaceable is not None:
                compact[replaceable] = item
        return sorted(compact, key=lambda result: result.ranking_score, reverse=True)


# Compatibility import retained for older tests/integrations.
RetrievalResult = RetrievedClause
