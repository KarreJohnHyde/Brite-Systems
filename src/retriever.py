"""
Retriever with optional reranking.

Takes a user question, searches the vector store, and optionally
reranks results using a cross-encoder for better precision.
"""

from dataclasses import dataclass
from typing import Optional

from src.parser import PolicyClause
from src.embeddings import EmbeddingEngine
from src.vector_store import VectorStore


@dataclass
class RetrievalResult:
    """A single retrieval result with scores."""
    clause: PolicyClause
    similarity_score: float          # FAISS cosine similarity
    rerank_score: Optional[float]    # Cross-encoder score (if reranking enabled)

    @property
    def final_score(self) -> float:
        """The best available score for ranking."""
        return self.rerank_score if self.rerank_score is not None else self.similarity_score


class Retriever:
    """Semantic retriever with optional cross-encoder reranking."""

    def __init__(
        self,
        embedding_engine: EmbeddingEngine,
        vector_store: VectorStore,
        use_reranker: bool = True,
        initial_k: int = 15,
        final_k: int = 5,
    ):
        self.embedding_engine = embedding_engine
        self.vector_store = vector_store
        self.use_reranker = use_reranker
        self.initial_k = initial_k
        self.final_k = final_k
        self.reranker = None

        if use_reranker:
            self._load_reranker()

    def _load_reranker(self):
        """Load the cross-encoder reranker model."""
        try:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as e:
            print(f"Warning: Could not load reranker ({e}). Falling back to embedding-only retrieval.")
            self.use_reranker = False
            self.reranker = None

    def retrieve(self, question: str) -> list[RetrievalResult]:
        """
        Retrieve the most relevant policy clauses for a question.
        
        Pipeline:
        1. Encode question → embedding
        2. FAISS search → top initial_k candidates
        3. (Optional) Cross-encoder rerank → top final_k results
        
        Returns: list of RetrievalResult sorted by final_score descending.
        """
        # Step 1: Encode the question
        query_embedding = self.embedding_engine.encode_query(question)

        # Step 2: FAISS search for initial candidates
        k = self.initial_k if self.use_reranker else self.final_k
        raw_results = self.vector_store.search(query_embedding, k=k)

        # Step 3: Optional reranking
        if self.use_reranker and self.reranker is not None and raw_results:
            results = self._rerank(question, raw_results)
        else:
            results = [
                RetrievalResult(
                    clause=clause,
                    similarity_score=score,
                    rerank_score=None,
                )
                for clause, score in raw_results
            ]

        # Sort by final score and return top final_k
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:self.final_k]

    def _rerank(
        self, question: str, candidates: list[tuple[PolicyClause, float]]
    ) -> list[RetrievalResult]:
        """Rerank candidates using the cross-encoder."""
        from src.parser import get_embedding_text

        # Prepare pairs for cross-encoder
        pairs = [(question, c.display_text()) for c, _ in candidates]
        
        # Get cross-encoder scores
        rerank_scores = self.reranker.predict(pairs)

        results = []
        for (clause, sim_score), rerank_score in zip(candidates, rerank_scores):
            results.append(RetrievalResult(
                clause=clause,
                similarity_score=sim_score,
                rerank_score=float(rerank_score),
            ))

        return results
