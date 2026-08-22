"""
Embedding engine for policy clauses.

Uses sentence-transformers to convert clause text into dense vectors
for semantic similarity search.
"""

from sentence_transformers import SentenceTransformer
import numpy as np

from src.parser import PolicyClause, get_embedding_text

# Default model — good balance of quality and speed
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingEngine:
    """Manages embedding model and clause encoding."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_embedding_dimension()

    def encode_clauses(self, clauses: list[PolicyClause]) -> np.ndarray:
        """
        Encode a list of policy clauses into embeddings.
        
        Uses the full contextual text (clause ID + part + section + text + sub-items)
        to capture semantic meaning within the policy hierarchy.
        
        Returns: np.ndarray of shape (n_clauses, dimension), float32, L2-normalized.
        """
        texts = [get_embedding_text(c) for c in clauses]
        embeddings = self.model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,  # L2 normalize for cosine sim via inner product
        )
        return embeddings.astype("float32")

    def encode_query(self, query: str) -> np.ndarray:
        """
        Encode a user question into an embedding vector.
        
        Returns: np.ndarray of shape (1, dimension), float32, L2-normalized.
        """
        embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embedding.astype("float32")
